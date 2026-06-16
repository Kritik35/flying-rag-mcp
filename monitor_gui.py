"""
monitor_gui.py — Легковесный GUI-монитор для Flying RAG MCP.
Построен на tkinter (стандартная библиотека) для 100% переносимости на Windows.
"""
from __future__ import annotations
import os
import sys
import time
import yaml
import threading
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

CONFIG_PATH = ROOT / "config.yaml"
LOG_PATH = ROOT / "storage" / "flying_rag.log"


class RagMonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Flying RAG MCP — Панель управления")
        self.geometry("750x550")
        self.configure(bg="#f4f5f7")

        # Современные стили ttk
        self.style = ttk.Style()
        self.style.theme_use("vista")
        self.style.configure("TLabel", background="#f4f5f7", font=("Segoe UI", 10))
        self.style.configure("TButton", font=("Segoe UI", 9))
        self.style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))

        self._cfg = self._load_config()

        self._create_widgets()
        self._start_background_checks()
        self._check_indexing_progress()

    def _load_config(self) -> dict:
        if not CONFIG_PATH.exists():
            return {"watched_folders": [], "lemonade": {"base_url": "http://localhost:13305/api/v1/embeddings"}}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            try:
                return yaml.safe_load(f) or {}
            except Exception:
                return {"watched_folders": []}

    def _save_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._cfg, f, allow_unicode=True)

    def _create_widgets(self):
        # 1. Заголовок и Статус Lemonade
        header_frame = tk.Frame(self, bg="#ffffff", bd=1, relief="groove")
        header_frame.pack(fill="x", padx=10, pady=10)

        title_lbl = ttk.Label(header_frame, text="Flying RAG MCP Монитор", style="Header.TLabel", background="#ffffff")
        title_lbl.pack(side="left", padx=10, pady=10)

        # Индикатор Lemonade
        self.lemonade_status_lbl = tk.Label(
            header_frame, text="Lemonade: ПРОВЕРКА...", bg="#ffc107", fg="#000000",
            font=("Segoe UI", 9, "bold"), padx=8, pady=4, bd=0
        )
        self.lemonade_status_lbl.pack(side="right", padx=10, pady=10)

        self.btn_start_lemonade = ttk.Button(header_frame, text="Запустить Lemonade", command=self._start_lemonade_server)
        self.btn_start_lemonade.pack(side="right", padx=5, pady=10)

        # 2. Таблица watched folders
        table_frame = tk.LabelFrame(self, text=" Наблюдаемые директории (watched_folders) ", bg="#f4f5f7", font=("Segoe UI", 10, "bold"))
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Список папок
        self.folder_listbox = tk.Listbox(table_frame, font=("Segoe UI", 9), bd=1, selectmode="single")
        self.folder_listbox.pack(fill="both", expand=True, side="left", padx=10, pady=10)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.folder_listbox.yview)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=10)
        self.folder_listbox.config(yscrollcommand=scrollbar.set)

        self._refresh_folders_list()

        # Кнопки управления папками
        btn_frame = tk.Frame(self, bg="#f4f5f7")
        btn_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(btn_frame, text="Добавить папку", command=self._add_folder).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Удалить выбранную", command=self._remove_folder).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Запустить индексацию папки", command=self._trigger_indexing).pack(side="right", padx=5)

        # 3. Панель прогресса индексации
        self.progress_frame = tk.LabelFrame(self, text=" Прогресс индексации ", bg="#f4f5f7", font=("Segoe UI", 10, "bold"))
        self.progress_frame.pack(fill="x", padx=10, pady=5)

        self.progress_lbl = ttk.Label(self.progress_frame, text="База знаний актуальна. Новых задач нет.", font=("Segoe UI", 9))
        self.progress_lbl.pack(fill="x", padx=10, pady=5)

        self.progress_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", padx=10, pady=5)

        # 4. Логгер в реальном времени
        log_frame = tk.LabelFrame(self, text=" Фоновые логи (flying_rag.log) ", bg="#f4f5f7", font=("Segoe UI", 10, "bold"))
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.log_text = tk.Text(log_frame, wrap="word", height=8, font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)

    def _detect_dataset(self, path_str: str) -> str:
        datasets_cfg = self._cfg.get("datasets", {})
        path_str_normalized = path_str.replace("\\", "/")
        for ds_name, ds_cfg in datasets_cfg.items():
            if ds_name == "default":
                continue
            for p in ds_cfg.get("paths", []):
                if p.replace("\\", "/") in path_str_normalized:
                    return ds_name
        return datasets_cfg.get("default", "normative")

    def _refresh_folders_list(self):
        self.folder_listbox.delete(0, "end")
        folders = self._cfg.get("watched_folders", [])
        for f in folders:
            ds = self._detect_dataset(f)
            self.folder_listbox.insert("end", f"[{ds.upper()}]  {f}")

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку для индексации")
        if not folder:
            return
        folder_path = Path(folder).resolve()
        folders = self._cfg.get("watched_folders", [])
        if str(folder_path) in folders:
            messagebox.showinfo("Инфо", "Эта папка уже отслеживается!")
            return
        folders.append(str(folder_path))
        self._cfg["watched_folders"] = folders
        self._save_config()
        self._refresh_folders_list()
        # Запускаем индексацию добавленной папки
        self._run_indexer(folder_path)

    def _remove_folder(self):
        selected = self.folder_listbox.curselection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите папку из списка для удаления!")
            return
        idx = selected[0]
        selected_text = self.folder_listbox.get(idx)
        if selected_text.startswith("[") and "] " in selected_text:
            folder = selected_text.split("] ", 1)[1].strip()
        else:
            folder = selected_text
        if messagebox.askyesno("Подтверждение", f"Удалить папку из мониторинга?\n{folder}"):
            folders = self._cfg.get("watched_folders", [])
            if folder in folders:
                folders.remove(folder)
            self._cfg["watched_folders"] = folders
            self._save_config()
            self._refresh_folders_list()

    def _trigger_indexing(self):
        selected = self.folder_listbox.curselection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите папку из списка для индексации!")
            return
        idx = selected[0]
        selected_text = self.folder_listbox.get(idx)
        if selected_text.startswith("[") and "] " in selected_text:
            folder = selected_text.split("] ", 1)[1].strip()
        else:
            folder = selected_text
        self._run_indexer(Path(folder))

    def _run_indexer(self, path: Path):
        indexer_script = ROOT / "indexer.py"
        CREATE_NO_WINDOW = 0x08000000
        try:
            # Открываем лог-файл в режиме добавления (a)
            with open(LOG_PATH, "a", encoding="utf-8") as log_file:
                proc = subprocess.Popen(
                    [sys.executable, str(indexer_script), str(path)],
                    stdout=log_file,
                    stderr=log_file,
                    creationflags=CREATE_NO_WINDOW
                )
            messagebox.showinfo("Успех", f"Индексация запущена в фоне (PID: {proc.pid}).\nСледите за прогрессом в окне логов.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось запустить indexer.py:\n{e}")

    def _start_lemonade_server(self):
        try:
            # Запускаем lemonade-server в фоновом режиме на Windows
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(
                ["lemonade-server", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW
            )
            messagebox.showinfo("Успех", "Запрос на запуск lemonade-server отправлен в ОС.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось запустить lemonade-server:\nУбедитесь, что исполняемый файл доступен в PATH.\nДетали: {e}")

    def _start_background_checks(self):
        # 1. Поток проверки коннекта к Lemonade
        def _check_lemonade_loop():
            from embedder.client import check_connection
            while True:
                is_online = check_connection()
                self.after(0, self._update_lemonade_ui, is_online)
                time.sleep(2.0)

        t_lemonade = threading.Thread(target=_check_lemonade_loop, daemon=True)
        t_lemonade.start()

        # 2. Поток чтения логов (tail -n 50)
        def _tail_log_loop():
            while True:
                if LOG_PATH.exists():
                    try:
                        with open(LOG_PATH, "r", encoding="utf-8") as f:
                            # Читаем последние 2000 символов
                            f.seek(0, os.SEEK_END)
                            size = f.tell()
                            offset = min(size, 4000)
                            f.seek(size - offset)
                            lines = f.readlines()
                            # Ограничиваем последние 100 строк
                            last_lines = "".join(lines[-100:])
                            self.after(0, self._update_log_ui, last_lines)
                    except Exception:
                        pass
                time.sleep(1.0)

        t_log = threading.Thread(target=_tail_log_loop, daemon=True)
        t_log.start()

    def _update_lemonade_ui(self, is_online: bool):
        if is_online:
            self.lemonade_status_lbl.config(text="Lemonade: ONLINE", bg="#28a745", fg="#ffffff")
        else:
            self.lemonade_status_lbl.config(text="Lemonade: OFFLINE", bg="#dc3545", fg="#ffffff")

    def _update_log_ui(self, text: str):
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def _check_indexing_progress(self):
        try:
            from storage.metadata_db import get_active_indexing_progress
            db_name = self._cfg.get("storage", {}).get("metadata_db", "data/metadata.db")
            db_path = ROOT / db_name
            progress = get_active_indexing_progress(db_path)
            if progress:
                total = progress["total_files"]
                processed = progress["processed_files"]
                path = progress["path"]
                last_file = progress["last_file"]
                percent = (processed / total * 100) if total > 0 else 0
                
                self.progress_lbl.config(
                    text=f"Индексируем: {Path(path).name}\n"
                         f"Обработано файлов: {processed} из {total} ({percent:.1f}%)\n"
                         f"Текущий файл: {last_file}"
                )
                self.progress_bar["value"] = percent
            else:
                self.progress_lbl.config(text="База знаний актуальна. Задачи индексации отсутствуют.")
                self.progress_bar["value"] = 0
        except Exception as e:
            self.progress_lbl.config(text=f"Статус индексации: не удалось проверить БД ({e})")
            
        self.after(1000, self._check_indexing_progress)


if __name__ == "__main__":
    app = RagMonitorApp()
    app.mainloop()
