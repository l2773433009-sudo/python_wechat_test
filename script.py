import threading
import time
import tkinter as tk
from tkinter import scrolledtext, messagebox
from PIL import Image, ImageTk
import io

try:
    from wcflink import WcfLinkClient
except ImportError:
    WcfLinkClient = None

class WeChatForwarderApp:
    def __init__(self, master):
        self.master = master
        master.title("微信消息监听与转发 (wcflink)")
        self.client = None
        self.account_id = None
        self.handled_event_ids = set()
        self.target_id = None
        self.is_logged_in = False
        self.qr_popup = None

        self.status_var = tk.StringVar()
        self.status_var.set("[未登录]")
        self.status_label = tk.Label(master, textvariable=self.status_var, fg="red", font=("Arial", 11, "bold"))
        self.status_label.pack(pady=2)

        self.text_area = scrolledtext.ScrolledText(master, width=80, height=20, state='disabled')
        self.text_area.pack(padx=10, pady=10)

        self.target_entry = tk.Entry(master, width=50, state='disabled')
        self.target_entry.pack(padx=10, pady=5)
        self.target_entry.insert(0, "在此输入转发目标ID（如群ID或个人ID）")

        self.set_target_btn = tk.Button(master, text="设置转发目标", command=lambda: self._wrap_login_required(self.set_target)(), state='disabled')
        self.set_target_btn.pack(pady=2)

        self.qr_label = tk.Label(master)
        self.qr_label.pack(pady=2)

        self.list_contacts_btn = tk.Button(master, text="显示好友/群组列表", command=lambda: self._wrap_login_required(self.show_contacts)(), state='disabled')
        self.list_contacts_btn.pack(pady=2)

        self.logout_btn = tk.Button(master, text="退出登录", command=self.logout, state='disabled', fg='red')
        self.logout_btn.pack(pady=2)

        self.stop_flag = threading.Event()
        self.listen_thread = None
        self.contacts_window = None
        # 启动时自动检测并监听
        self.auto_start_listen()

    def _wrap_login_required(self, func):
        def wrapper(*args, **kwargs):
            if not self.is_logged_in:
                self.show_qr_popup()
                return
            return func(*args, **kwargs)
        return wrapper

    def set_target(self):
        self.target_id = self.target_entry.get().strip()
        messagebox.showinfo("设置成功", f"转发目标已设置为: {self.target_id}")

    def auto_start_listen(self):
        if not WcfLinkClient:
            messagebox.showerror("缺少依赖", "请先在命令行执行: pip install wcflink")
            return
        if self.listen_thread and self.listen_thread.is_alive():
            return
        self.stop_flag.clear()
        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()
        self.append_text("[系统] 已自动启动消息监听\n")

    def listen_loop(self):
        try:
            self.client = WcfLinkClient("http://127.0.0.1:17890")
            accounts = self.client.list_accounts()
            self.append_text(f"[系统] 检测到账号列表: {accounts}\n")
            # 优先选择个人微信号
            selected_account = None
            for acc in accounts:
                acc_id = getattr(acc, 'account_id', acc)
                if acc_id.endswith('@im.wechat') or acc_id.startswith('wxid_'):
                    selected_account = acc
                    break
            if not selected_account and accounts:
                # 退而选第一个
                selected_account = accounts[0]
            if not accounts:
                # 未登录，弹出二维码弹窗并阻塞
                session = self.client.start_login()
                self.append_text("[系统] 未检测到已登录账号，请扫码登录\n")
                self.show_qr_popup(session.session_id)
                # 阻塞直到扫码成功
                for _ in range(60):
                    status = self.client.get_login_status(session.session_id)
                    if getattr(status, 'status', None) == "authed":
                        self.append_text("[系统] 登录成功\n")
                        self.is_logged_in = True
                        self.master.after(0, self.enable_main_ui)
                        self.master.after(0, lambda: self.status_var.set("[已登录]"))
                        self.master.after(0, lambda: self.status_label.config(fg="green"))
                        self.master.after(0, lambda: messagebox.showinfo("登录成功", "微信已登录成功，可以开始操作！"))
                        self.close_qr_popup()
                        break
                    time.sleep(2)
                else:
                    self.append_text("[系统] 登录超时\n")
                    self.close_qr_popup()
                    return
                accounts = self.client.list_accounts()
                self.append_text(f"[系统] 登录后账号列表: {accounts}\n")
                # 重新选择
                selected_account = None
                for acc in accounts:
                    acc_id = getattr(acc, 'account_id', acc)
                    if acc_id.endswith('@im.wechat') or acc_id.startswith('wxid_'):
                        selected_account = acc
                        break
                if not selected_account and accounts:
                    selected_account = accounts[0]
                if not accounts:
                    self.append_text("[系统] 登录后未检测到账号\n")
                    return
            self.account_id = getattr(selected_account, 'account_id', selected_account)
            self.append_text(f"[系统] 当前账号: {self.account_id}\n")
            if self.account_id.endswith('@im.bot'):
                self.append_text("[警告] 当前监听的是 bot 账号，无法收到你个人微信的消息！请确保扫码的是你的个人微信号。\n")
            self.is_logged_in = True
            self.master.after(0, self.enable_main_ui)
            self.master.after(0, lambda: self.status_var.set("[已登录]"))
            self.master.after(0, lambda: self.status_label.config(fg="green"))
            self.master.after(0, lambda: messagebox.showinfo("登录成功", "微信已登录成功，可以开始操作！"))
            self.close_qr_popup()
        except Exception as e:
            self.append_text(f"[错误] 连接 wcflink 失败: {e}\n")
            return
        while not self.stop_flag.is_set():
            try:
                events = self.client.list_events(limit=10)
                for event in events:
                    event_id = getattr(event, 'event_id', None)
                    if event_id and event_id not in self.handled_event_ids:
                        self.handle_event(event)
                        self.handled_event_ids.add(event_id)
            except Exception as e:
                self.append_text(f"[错误] 监听异常: {e}\n")
            time.sleep(2)

    def show_qr_popup(self, session_id=None):
        if self.qr_popup and tk.Toplevel.winfo_exists(self.qr_popup):
            self.qr_popup.lift()
            return
        self.qr_popup = tk.Toplevel(self.master)
        self.qr_popup.title("请扫码登录微信")
        self.qr_popup.geometry("300x350")
        self.qr_popup.transient(self.master)
        self.qr_popup.grab_set()
        label = tk.Label(self.qr_popup, text="请使用微信扫码登录", font=("Arial", 12))
        label.pack(pady=10)
        qr_img_label = tk.Label(self.qr_popup)
        qr_img_label.pack(pady=10)
        # 获取二维码
        if not session_id:
            try:
                session = self.client.start_login()
                session_id = session.session_id
            except Exception as e:
                qr_img_label.config(text=f"二维码获取失败: {e}")
                return
        try:
            png = self.client.get_login_qr(session_id)
            image = Image.open(io.BytesIO(png))
            image = image.resize((256, 256))
            photo = ImageTk.PhotoImage(image)
            qr_img_label.config(image=photo)
            qr_img_label.image = photo
        except Exception as e:
            qr_img_label.config(text=f"二维码加载失败: {e}")
        self.qr_popup.protocol("WM_DELETE_WINDOW", lambda: None)  # 禁止关闭
        self.disable_main_ui()

    def close_qr_popup(self):
        if self.qr_popup and tk.Toplevel.winfo_exists(self.qr_popup):
            self.qr_popup.grab_release()
            self.qr_popup.destroy()
            self.qr_popup = None

    def enable_main_ui(self):
        self.set_target_btn.config(state='normal')
        self.list_contacts_btn.config(state='normal')
        self.target_entry.config(state='normal')
        self.logout_btn.config(state='normal')

    def disable_main_ui(self):
        self.set_target_btn.config(state='disabled')
        self.list_contacts_btn.config(state='disabled')
        self.target_entry.config(state='disabled')
        self.logout_btn.config(state='disabled')

    def logout(self):
        try:
            import requests
        except ImportError:
            messagebox.showerror("缺少依赖", "退出登录需要 requests 库，请在命令行执行: pip install requests")
            return
        try:
            # 获取当前账号id
            account_id = self.account_id
            if not account_id:
                messagebox.showinfo("未登录", "当前无已登录账号")
                return
            # 调用 HTTP API 退出登录
            url = f"http://127.0.0.1:17890/api/accounts/logout"
            resp = requests.post(url, json={"account_id": account_id}, timeout=5)
            if resp.status_code == 200:
                messagebox.showinfo("退出成功", "已退出登录，请重新扫码登录")
            else:
                messagebox.showwarning("退出失败", f"退出登录失败: {resp.text}")
        except Exception as e:
            messagebox.showwarning("退出失败", f"退出登录失败: {e}\n请手动删除 data 目录下账号数据后重启 wcflink 服务。")
        # 重置状态，弹出二维码
        self.is_logged_in = False
        self.status_var.set("[未登录]")
        self.status_label.config(fg="red")
        self.disable_main_ui()
        self.show_qr_popup()

    def handle_event(self, event):
        if getattr(event, 'type', None) == "message.text":
            data = getattr(event, 'data', {})
            from_user = data.get('from_user_id') if isinstance(data, dict) else getattr(data, 'from_user_id', None)
            text = data.get('text') if isinstance(data, dict) else getattr(data, 'text', None)
            is_group = data.get('is_group', False) if isinstance(data, dict) else getattr(data, 'is_group', False)
            msg = f"[{'群' if is_group else '私聊'}] {from_user}: {text}\n"
            self.append_text(msg)
            # 自动转发（可选）
            if self.target_id and from_user != self.account_id:
                try:
                    self.client.send_text(
                        account_id=self.account_id,
                        to_user_id=self.target_id,
                        text=f"[转发]{text}",
                    )
                    self.append_text(f"[系统] 已转发到 {self.target_id}\n")
                except Exception as e:
                    self.append_text(f"[转发失败] {e}\n")
        # 支持多目标转发
        if self.target_id:
            targets = [tid.strip() for tid in self.target_id.split(',') if tid.strip()]
            for target in targets:
                if from_user != self.account_id and target:
                    try:
                        self.client.send_text(
                            account_id=self.account_id,
                            to_user_id=target,
                            text=f"[转发]{text}",
                        )
                        self.append_text(f"[系统] 已转发到 {target}\n")
                    except Exception as e:
                        self.append_text(f"[转发失败] {e}\n")

    def append_text(self, msg):
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, msg)
        self.text_area.see(tk.END)
        self.text_area.config(state='disabled')

if __name__ == '__main__':
    root = tk.Tk()
    app = WeChatForwarderApp(root)
    root.mainloop()
