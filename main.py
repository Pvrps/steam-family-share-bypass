import customtkinter as ctk
import winreg
import os
import sys
import shutil
import subprocess
import threading
import time
from tkinter import messagebox
from typing import List, Optional, Tuple
import json

import requests
import re
from bs4 import BeautifulSoup

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

PATCH_SUBDIR = "patch"
PATCH_DLL_NAME = "user32.dll"
CACHE_CLEANER_EXE_NAME = "DeleteSteamAppCache.exe"
STEAM_EXE = "steam.exe"
VC_REDIST_EXE_NAME = "VC_redist.x86.exe"
APP_LIST_DIR_NAME = "AppList"
AUTHOR = "Purps"

VC_REDIST_REG_KEY = r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x86"
VC_REDIST_REG_VALUE = "Installed"

PATCH_DLL = get_resource_path(os.path.join(PATCH_SUBDIR, PATCH_DLL_NAME))
CACHE_CLEANER_EXE = get_resource_path(os.path.join(PATCH_SUBDIR, CACHE_CLEANER_EXE_NAME))
VC_REDIST_EXE = get_resource_path(os.path.join(PATCH_SUBDIR, VC_REDIST_EXE_NAME))

query_filter = re.compile("[^a-zA-Z0-9]")

class SteamGame:
    def __init__(self, app_id: str, name: str, type: str):
        self.id = app_id.strip()
        self.name = name.strip()
        self.type = type.strip()
    def __repr__(self):
        return f"SteamGame(id={self.id}, name='{self.name}', type='{self.type}')"

def get_game_details_by_id(app_id: str) -> Optional[SteamGame]:
    """Fetches game details for a given app ID from the Steam API."""
    if not app_id.isdigit(): return None
    try:
        url = "https://store.steampowered.com/api/appdetails"
        params = {"appids": app_id}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and data.get(app_id, {}).get("success"):
            game_data = data[app_id]["data"]
            return SteamGame(app_id=str(game_data["steam_appid"]), name=game_data["name"], type=game_data.get("type", "unknown").capitalize())
        return SteamGame(app_id=app_id, name=f"Unknown Game", type="Unknown")
    except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
        print(f"Could not retrieve details for appid {app_id}. Error: {e}")
        return SteamGame(app_id=app_id, name=f"Unknown Game", type="Unknown")

def parse_steam_dlcs(html: str) -> List[SteamGame]:
    soup = BeautifulSoup(html, "html.parser")
    dlcs = soup.find_all("div", class_="recommendation")
    games = []
    for dlc in dlcs:
        if dlc.find("a"):
            appid = dlc.find("a")["data-ds-appid"]
            name = dlc.find("span", class_="color_created").get_text()
            games.append(SteamGame(appid, name, "DLC"))
    return games

def get_steam_dlcs(store_url: str) -> List[SteamGame]:
    if "app/" not in store_url: return []
    try:
        app_info = store_url.split("app/")[1].split("/")
        appid, sanitazed_name = app_info[0], app_info[1]
        params = {"sort": "newreleases", "count": 64, "start": 0}
        base_url = f"https://store.steampowered.com/dlc/{appid}/{sanitazed_name}/ajaxgetfilteredrecommendations"
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        return parse_steam_dlcs(response.json().get("results_html", ""))
    except (requests.RequestException, KeyError) as e:
        print(f"Could not retrieve DLCs for {store_url}. Error: {e}")
        return []

def parse_steam_games(html: str, query: str) -> List[SteamGame]:
    clean_query = query_filter.sub("", query.lower())
    soup = BeautifulSoup(html, "html.parser")
    results = soup.find_all("a", class_="search_result_row")
    games = []
    for result in results:
        if result.has_attr("data-ds-appid"):
            appid = result["data-ds-appid"]
            name = result.find("span", class_="title").get_text()
            if "," not in appid and clean_query in query_filter.sub("", name.lower()):
                games.append(SteamGame(appid, name, "Game"))
                dlcs = get_steam_dlcs(result["href"])
                if dlcs: games.extend(dlcs)
    return games

def search_steam_for_games(query: str) -> List[SteamGame]:
    try:
        params = {"term": query, "count": 25, "start": 0, "category1": 998}
        response = requests.get("https://store.steampowered.com/search/results", params=params, timeout=10)
        response.raise_for_status()
        return parse_steam_games(response.text, query)
    except requests.RequestException as e:
        print(f"An error occurred during Steam search: {e}")
        return []

class SteamPatcherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"Steam Patcher by {AUTHOR}")
        self.geometry("600x650")
        self.minsize(550, 550)
        ctk.set_appearance_mode("dark")

        self.steam_path: Optional[str] = None
        self.is_steam_installed = False
        self.is_patched = False
        self.current_game_list: List[Tuple[str, str]] = []
        self.pending_game_list: List[Tuple[str, str]] = []
        self.changes_pending = False
        
        self.is_steam_running = threading.Event()
        self.running = threading.Event()
        self.running.set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_ui()
        self.update_all_statuses()
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self): self.running.clear(); self.destroy()

    def _build_ui(self):
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(top_frame, text="Steam Patcher Utility", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(0,0))
        ctk.CTkLabel(top_frame, text=f"by {AUTHOR}", font=ctk.CTkFont(size=12), text_color="gray").pack(pady=(0, 5))

        self.tab_view = ctk.CTkTabview(self); self.tab_view.grid(row=1, column=0, padx=10, pady=0, sticky="nsew"); self.tab_view.add("Patcher")
        patcher_tab = self.tab_view.tab("Patcher"); patcher_tab.grid_columnconfigure(0, weight=1); patcher_tab.grid_rowconfigure(1, weight=1)
        status_frame = ctk.CTkFrame(patcher_tab); status_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew"); status_frame.grid_columnconfigure(0, weight=1)

        self.path_label = ctk.CTkLabel(status_frame, text="Steam Path: Checking...", anchor="w"); self.path_label.grid(row=0, column=0, columnspan=2, padx=10, pady=2, sticky="w")
        self.patch_status_label = ctk.CTkLabel(status_frame, text="Patch Status: Checking...", anchor="w"); self.patch_status_label.grid(row=2, column=0, columnspan=2, padx=10, pady=2, sticky="w")
        self.patch_button = ctk.CTkButton(status_frame, text="Patch Steam", font=ctk.CTkFont(weight="bold"), command=lambda: self.run_threaded_action(self.patching_process)); self.patch_button.grid(row=3, column=0, pady=10, padx=10, sticky="ew")
        self.unpatch_button = ctk.CTkButton(status_frame, text="Unpatch Steam", font=ctk.CTkFont(weight="bold"), command=lambda: self.run_threaded_action(self.unpatching_process), fg_color="#D32F2F", hover_color="#B71C1C"); self.unpatch_button.grid(row=3, column=1, pady=10, padx=10, sticky="ew")
        
        log_frame = ctk.CTkFrame(patcher_tab); log_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew"); log_frame.grid_columnconfigure(0, weight=1); log_frame.grid_rowconfigure(0, weight=1)
        self.status_textbox = ctk.CTkTextbox(log_frame, state="disabled", font=("Consolas", 12)); self.status_textbox.grid(row=0, column=0, sticky="nsew")

    def _build_game_management_tab(self):
        if "Game Management" in self.tab_view._tab_dict: return
        self.tab_view.add("Game Management")
        game_tab = self.tab_view.tab("Game Management")
        game_tab.grid_columnconfigure(0, weight=1); game_tab.grid_rowconfigure(2, weight=1)

        search_frame = ctk.CTkFrame(game_tab); search_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew"); search_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(search_frame, text="Search for Games by Name", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(5,0))
        self.search_game_entry = ctk.CTkEntry(search_frame, placeholder_text="e.g., Cyberpunk 2077"); self.search_game_entry.grid(row=1, column=0, padx=(10,5), pady=10, sticky="ew")
        self.search_game_button = ctk.CTkButton(search_frame, text="🔎 Search", width=100, command=self.search_for_games); self.search_game_button.grid(row=1, column=1, padx=(0,10), pady=10)

        add_frame = ctk.CTkFrame(game_tab); add_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew"); add_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(add_frame, text="Add Games by App ID", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(5,0))
        self.add_game_entry = ctk.CTkEntry(add_frame, placeholder_text="Enter App ID(s), comma or space separated"); self.add_game_entry.grid(row=1, column=0, padx=(10,5), pady=10, sticky="ew")
        self.add_game_button = ctk.CTkButton(add_frame, text="➕ Add ID", width=100, command=self.add_games_from_entry); self.add_game_button.grid(row=1, column=1, padx=(0,10), pady=10)
        
        self.scrollable_game_list = ctk.CTkScrollableFrame(game_tab, label_text="Pending Game List"); self.scrollable_game_list.grid(row=2, column=0, padx=10, pady=0, sticky="nsew")
        save_frame = ctk.CTkFrame(game_tab); save_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew"); save_frame.grid_columnconfigure(0, weight=1); save_frame.grid_columnconfigure(1, weight=1)
        self.save_button = ctk.CTkButton(save_frame, text="✅ Apply Changes", command=self.save_game_list_changes, state="disabled"); self.save_button.grid(row=0, column=0, padx=(10,5), pady=5, sticky="ew")
        self.cancel_button = ctk.CTkButton(save_frame, text="❌ Cancel", command=self.cancel_game_list_changes, fg_color="#585858", hover_color="#424242", state="disabled"); self.cancel_button.grid(row=0, column=1, padx=(5,10), pady=5, sticky="ew")

    def _remove_game_management_tab(self):
        try:
            if self.tab_view.get() == "Game Management": self.tab_view.set("Patcher")
            self.tab_view.delete("Game Management")
        except: pass

    def run_threaded_action(self, target_function, *args): self.disable_all_buttons(); threading.Thread(target=target_function, args=args, daemon=True).start()
    def log_message(self, message): self.after(0, lambda: self.status_textbox.configure(state="normal") or self.status_textbox.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n") or self.status_textbox.configure(state="disabled") or self.status_textbox.see("end"))

    def disable_all_buttons(self, disabled=True):
        state = "disabled" if disabled else "normal"
        self.patch_button.configure(state=state); self.unpatch_button.configure(state=state)
        if "Game Management" in self.tab_view._tab_dict:
            self.add_game_button.configure(state=state); self.search_game_button.configure(state=state)
            self.save_button.configure(state=state if self.changes_pending else "disabled"); self.cancel_button.configure(state=state if self.changes_pending else "disabled")
            for frame in self.scrollable_game_list.winfo_children():
                for widget in frame.winfo_children():
                    if isinstance(widget, ctk.CTkButton): widget.configure(state=state)

    def update_ui_states(self):
        self.path_label.configure(text=f"Steam Path: {self.steam_path if self.is_steam_installed else 'Not Found'}", text_color="green" if self.is_steam_installed else "red")
        if self.is_patched:
            self.patch_status_label.configure(text="Patch Status: Patched", text_color="green"); self.patch_button.grid_remove(); self.unpatch_button.grid(); self._build_game_management_tab()
        else:
            self.patch_status_label.configure(text="Patch Status: Not Patched", text_color="orange"); self.patch_button.grid(); self.unpatch_button.grid_remove(); self._remove_game_management_tab()
        self.disable_all_buttons(False)
        self.patch_button.configure(state="disabled" if not self.is_steam_installed or self.is_patched else "normal")
        self.unpatch_button.configure(state="disabled" if not self.is_patched else "normal")

    def update_all_statuses(self):
        self.log_message("Performing status checks..."); self.steam_path = get_steam_install_path()
        self.is_steam_installed = bool(self.steam_path); self.is_patched = os.path.exists(os.path.join(self.steam_path, PATCH_DLL_NAME)) if self.is_steam_installed else False
        self.after(0, self.update_ui_states)
        if self.is_patched: self.run_threaded_action(self.load_game_list_from_disk)
        else: self.log_message("Checks complete.")
            
    def load_game_list_from_disk(self):
        self.log_message("Loading existing game list...")
        id_list = []
        if self.steam_path and os.path.isdir(p := os.path.join(self.steam_path, APP_LIST_DIR_NAME)):
            files = sorted([f for f in os.listdir(p) if f.endswith('.txt')], key=lambda f: int(f.split('.')[0]))
            for filename in files:
                with open(os.path.join(p, filename), 'r') as f: id_list.append(f.read().strip())
        
        loaded_games = []
        if id_list:
            self.log_message(f"Found {len(id_list)} App IDs. Fetching names...")
            with threading.Lock():
                for app_id in id_list:
                    game = get_game_details_by_id(app_id)
                    if game: loaded_games.append((game.id, game.name))
        
        self.current_game_list = loaded_games
        self.pending_game_list = list(self.current_game_list)
        self.after(0, self.populate_scrollable_game_list)
        self.log_message("Game list loaded.")
        self.after(0, lambda: self.disable_all_buttons(False))

    def populate_scrollable_game_list(self):
        if "Game Management" not in self.tab_view._tab_dict: return
        for widget in self.scrollable_game_list.winfo_children(): widget.destroy()
        for app_id, name in self.pending_game_list:
            frame = ctk.CTkFrame(self.scrollable_game_list); frame.pack(fill="x", pady=2, padx=2)
            frame.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(frame, text=f"{name} ({app_id})", wraplength=400, justify="left").grid(row=0, column=0, padx=5, sticky="w")
            ctk.CTkButton(frame, text="➖", width=40, fg_color="#D32F2F", hover_color="#B71C1C", command=lambda a=app_id: self.remove_game_from_pending(a)).grid(row=0, column=1, padx=5)

    def set_changes_pending(self, pending: bool): self.changes_pending = pending; state = "normal" if pending else "disabled"; self.save_button.configure(state=state); self.cancel_button.configure(state=state)

    def add_games_to_pending(self, games_to_add: List[SteamGame]):
        added_count = 0
        pending_ids = [item[0] for item in self.pending_game_list]
        for game in games_to_add:
            if game.id not in pending_ids:
                self.pending_game_list.append((game.id, game.name)); added_count += 1
        if added_count > 0:
            self.log_message(f"Added {added_count} new item(s). Apply changes to save."); self.set_changes_pending(True); self.populate_scrollable_game_list()
        else: self.log_message("No new items were added (already in list).")

    def add_games_from_entry(self):
        raw_input = self.add_game_entry.get().replace(",", " ").strip()
        if not raw_input: return
        self.add_game_entry.delete(0, 'end')
        self.log_message("Fetching details for entered App ID(s)...")
        self.run_threaded_action(self.fetch_and_add_ids, raw_input.split())

    def fetch_and_add_ids(self, app_ids: List[str]):
        games_found = []
        for app_id in app_ids:
            if app_id.isdigit():
                game = get_game_details_by_id(app_id)
                if game: games_found.append(game)
        self.after(0, self.add_games_to_pending, games_found)
        self.after(0, lambda: self.disable_all_buttons(False))

    def remove_game_from_pending(self, app_id: str):
        game_to_remove = next((item for item in self.pending_game_list if item[0] == app_id), None)
        if game_to_remove: self.pending_game_list.remove(game_to_remove); self.log_message(f"Removed {game_to_remove[1]}. Apply to save."); self.set_changes_pending(True); self.populate_scrollable_game_list()
    
    def save_game_list_changes(self): self.run_threaded_action(self.modify_game_list_process)
    def cancel_game_list_changes(self): self.log_message("Cancelled all pending changes."); self.pending_game_list = list(self.current_game_list); self.set_changes_pending(False); self.populate_scrollable_game_list()
    def search_for_games(self):
        if not (q := self.search_game_entry.get()): self.log_message("Search query empty."); return
        self.log_message(f"Searching for '{q}'..."); self.run_threaded_action(self.execute_search, q)

    def execute_search(self, query: str):
        results = search_steam_for_games(query)
        self.log_message(f"Search for '{query}' complete. Found {len(results)} results.")
        self.after(0, self.show_search_results, query, results)

    def show_search_results(self, query: str, results: List[SteamGame]):
        if not results: self.log_message(f"No results found for '{query}'.")
        else:
            dialog = SearchResultsDialog(self, f"Results for '{query}'", results)
            if selected_games := dialog.get_selection(): self.add_games_to_pending(selected_games)
        self.disable_all_buttons(False)

    def patching_process(self):
        self.log_message("Starting patch process...")
        if not all(os.path.exists(p) for p in [PATCH_DLL]): self.log_message("Error: Required DLLs not found."); self.after(0, self.update_all_statuses); return
        if not kill_steam_process(self): self.log_message("Patching aborted."); self.after(0, self.update_all_statuses); return
        if not run_cache_cleaner(self): self.log_message("Patching aborted."); self.after(0, self.update_all_statuses); return
        try:
            shutil.copy(PATCH_DLL, os.path.join(self.steam_path, PATCH_DLL_NAME)); 
            app_list_dir = os.path.join(self.steam_path, APP_LIST_DIR_NAME); os.makedirs(app_list_dir, exist_ok=True)
            if not os.listdir(app_list_dir):
                with open(os.path.join(app_list_dir, "0.txt"), 'w') as f: f.write("480")
            self.log_message("Patch applied successfully."); self.after(0, lambda: self.tab_view.set("Game Management"))
        except Exception as e: self.log_message(f"Error during patching: {e}")
        start_steam_process(self); self.after(0, self.update_all_statuses)

    def unpatching_process(self):
        self.log_message("Starting unpatch process...")
        if not kill_steam_process(self): self.log_message("Unpatching aborted."); self.after(0, self.update_all_statuses); return
        try:
            for path in [os.path.join(self.steam_path, PATCH_DLL_NAME)]:
                if os.path.exists(path): os.remove(path)
            # if os.path.isdir(p := os.path.join(self.steam_path, APP_LIST_DIR_NAME)): shutil.rmtree(p)
            if not run_cache_cleaner(self): self.log_message("Failed to clean steam app cache."); self.after(0, self.update_all_statuses); return
            self.log_message("Unpatch successful.")
        except Exception as e: self.log_message(f"Error during unpatching: {e}")
        start_steam_process(self); self.after(0, self.update_all_statuses)
        
    def modify_game_list_process(self):
        self.log_message("Applying game list changes...")
        if not kill_steam_process(self): self.log_message("Update aborted."); self.after(0, self.update_all_statuses); return
        try:
            app_list_path = os.path.join(self.steam_path, APP_LIST_DIR_NAME)
            if os.path.isdir(app_list_path): shutil.rmtree(app_list_path)
            os.makedirs(app_list_path, exist_ok=True)
            for i, (app_id, _) in enumerate(self.pending_game_list):
                with open(os.path.join(app_list_path, f"{i}.txt"), 'w') as f: f.write(app_id)
            self.log_message("Successfully saved new game list."); self.current_game_list = list(self.pending_game_list)
            self.after(0, lambda: self.set_changes_pending(False))
        except Exception as e: self.log_message(f"Error modifying AppList files: {e}")
        if not run_cache_cleaner(self): self.log_message("Warning: Cache cleaner failed.")
        start_steam_process(self); self.after(0, self.update_ui_states)

class SearchResultsDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, results: List[SteamGame]):
        super().__init__(parent); self.title(title); self.geometry("500x400"); self.transient(parent); self.grab_set()
        self.selection: List[SteamGame] = []
        self.checkboxes: List[Tuple[ctk.CTkCheckBox, SteamGame]] = []
        scroll_frame = ctk.CTkScrollableFrame(self, label_text="Select games/DLCs to add"); scroll_frame.pack(expand=True, fill="both", padx=10, pady=10)
        for game in results:
            cb = ctk.CTkCheckBox(scroll_frame, text=f"[{game.type}] {game.name} ({game.id})"); cb.pack(fill="x", padx=5, pady=2); self.checkboxes.append((cb, game))
        button_frame = ctk.CTkFrame(self, fg_color="transparent"); button_frame.pack(fill="x", padx=10, pady=10); button_frame.grid_columnconfigure((0,1), weight=1)
        ctk.CTkButton(button_frame, text="Add Selected", command=self.confirm).grid(row=0, column=0, padx=(0,5), sticky="ew")
        ctk.CTkButton(button_frame, text="Cancel", fg_color="#585858", hover_color="#424242", command=self.cancel).grid(row=0, column=1, padx=(5,0), sticky="ew")
        self.wait_window()
    def confirm(self): self.selection = [game for cb, game in self.checkboxes if cb.get() == 1]; self.destroy()
    def cancel(self): self.selection = []; self.destroy()
    def get_selection(self) -> List[SteamGame]: return self.selection

def get_steam_install_path():
    try: key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"); steam_path, _ = winreg.QueryValueEx(key, "SteamPath"); winreg.CloseKey(key); return steam_path.replace("/", "\\")
    except: return None
def kill_steam_process(app: SteamPatcherApp):
    app.is_steam_running.clear(); return_val = True
    try: subprocess.run(["taskkill", "/F", "/IM", STEAM_EXE], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW); app.log_message("Steam process killed successfully."); time.sleep(1)
    except subprocess.CalledProcessError: app.log_message("Steam is not running or could not be killed.")
    return return_val
def start_steam_process(app: SteamPatcherApp):
    app.log_message("Starting Steam...")
    if app.steam_path:
        try: subprocess.Popen([os.path.join(app.steam_path, STEAM_EXE)]); app.log_message("Steam started successfully."); return True
        except FileNotFoundError: app.log_message("Error: steam.exe not found."); return False
    return False
def run_cache_cleaner(app: SteamPatcherApp):
    app.log_message("Running cache cleaner...")
    if not os.path.exists(CACHE_CLEANER_EXE): app.log_message(f"Error: '{CACHE_CLEANER_EXE_NAME}' not found."); return False
    try: process = subprocess.Popen([CACHE_CLEANER_EXE], creationflags=subprocess.CREATE_NO_WINDOW); process.wait(timeout=15); return process.returncode == 0
    except Exception as e: app.log_message(f"Error running cache cleaner: {e}"); return False
def is_vc_redist_installed():
    try: key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, VC_REDIST_REG_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY); value, _ = winreg.QueryValueEx(key, VC_REDIST_REG_VALUE); winreg.CloseKey(key); return value == 1
    except: return False
def run_vc_redist_installer():
    if not os.path.exists(VC_REDIST_EXE): messagebox.showerror("Fatal Error", f"'{VC_REDIST_EXE_NAME}' not found."); return False
    try: ret_code = subprocess.call([VC_REDIST_EXE, "/passive", "/norestart"]); return ret_code in [0, 3010]
    except Exception as e: messagebox.showerror("Fatal Error", f"Error running installer: {e}"); return False

if __name__ == "__main__":
    if not is_vc_redist_installed():
        root = ctk.CTk(); root.withdraw()
        if messagebox.askyesno("Prerequisite Missing", "The Visual C++ Redistributable is required. Would you like to install it now?"):
            if run_vc_redist_installer() and is_vc_redist_installed(): messagebox.showinfo("Success", "Prerequisite installed successfully. You may need to restart your PC.")
            else: messagebox.showerror("Error", "Prerequisite installation failed. The application cannot start."); sys.exit(1)
        else: sys.exit(0)
        root.destroy()
    app = SteamPatcherApp(); app.mainloop()