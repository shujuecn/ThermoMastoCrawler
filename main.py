import os
import re
import time
import csv
import json
import random
import threading
import concurrent.futures
import traceback
from urllib.parse import urljoin, urlparse

from dotenv import load_dotenv
import requests
import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import urllib3

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ThermoMastoCrawler:
    """
    一个风格统一、多线程、健壮的热成像乳腺数据爬虫。

    功能:
    1. 爬取图片库 (任务1)
    2. 爬取患者详情、元数据(JSON)和相关文件(图片/TXT) (任务2)
    """

    # --- 任务常量 ---
    TASK_GALLERY = "gallery"
    TASK_PATIENT = "patient"

    def __init__(self, username, password, driver_path="/usr/local/bin/chromedriver"):
        self.username = username
        self.password = password
        self.base_url = "https://visual.ic.uff.br/dmi/prontuario/"
        self.driver_path = driver_path
        self.driver = None

        # --- 反爬与健壮性设置 ---
        self.delay_range = (1.5, 3.5)  # 导航延迟范围 (秒)
        self.timeout = 30  # 下载超时
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
        ]

        # --- 共享会话和日志 ---
        self.session = self._setup_session()
        self.log_file = "download_log_unified.csv"
        self.log_lock = threading.Lock()  # 线程锁，用于安全写入日志和控制台输出
        self._init_log_file()

    ## ----------------------------------------------------------------
    ## 核心设置、初始化与日志
    ## ----------------------------------------------------------------

    def _log(self, level="INFO", message=""):
        """
        统一的、线程安全的日志输出到控制台。
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        prefix_map = {
            "INFO": "[INFO]",
            "WARN": "[WARN]",
            "ERROR": "[ERROR]",
            "SUCCESS": "[SUCCESS]",
            "DEBUG": "[DEBUG]",
        }
        prefix = prefix_map.get(level.upper(), f"[{level.upper()}]")

        # 使用现有的锁来确保 print 输出不会在多线程中交错
        with self.log_lock:
            print(f"{timestamp} {prefix} {message}")

    def _setup_session(self):
        """配置带重试和User-Agent的Requests Session"""
        session = requests.Session()
        session.verify = False
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods={"HEAD", "GET", "OPTIONS"},
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"User-Agent": random.choice(self.user_agents)})
        return session

    def _init_log_file(self):
        """初始化CSV日志文件，如果不存在则写入表头"""
        if not os.path.exists(self.log_file):
            with self.log_lock:
                with open(self.log_file, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            "timestamp",
                            "task_type",
                            "identifier",
                            "file_name",
                            "status",
                            "size_kb",
                            "url",
                            "elapsed_s",
                            "error",
                        ]
                    )

    def setup_driver(self):
        """设置Chrome驱动"""
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(f"--user-agent={random.choice(self.user_agents)}")

        service = Service(self.driver_path)
        try:
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.implicitly_wait(10)
            self._log("SUCCESS", "Chrome驱动初始化成功 (Headless)")
            return True
        except Exception as e:
            self._log("ERROR", f"Chrome驱动初始化失败: {e}")
            self._log("ERROR", "请确保chromedriver路径正确，或已安装webdriver-manager")
            return False

    def login(self):
        """使用Selenium登录并将会话Cookie同步到Requests"""
        try:
            self._log("INFO", "正在访问登录页面...")
            self.driver.get(f"{self.base_url}/index.php")
            time.sleep(random.uniform(0.5, 1.5))

            username_field = self.driver.find_element(
                By.CSS_SELECTOR, "input[type='text']"
            )
            password_field = self.driver.find_element(
                By.CSS_SELECTOR, "input[type='password']"
            )
            submit_button = self.driver.find_element(
                By.CSS_SELECTOR, "input[type='submit'], button[type='submit']"
            )

            username_field.clear()
            username_field.send_keys(self.username)
            password_field.clear()
            password_field.send_keys(self.password)
            submit_button.click()

            self._log("INFO", "正在等待登录...")
            time.sleep(random.uniform(3, 5))

            current_url = self.driver.current_url
            if "home.php" in current_url:
                self._log("SUCCESS", "登录成功！已进入主界面")

                # 关键一步：同步Cookie到Requests Session
                cookies = self.driver.get_cookies()
                for cookie in cookies:
                    self.session.cookies.set(cookie["name"], cookie["value"])
                self._log("INFO", f"已同步 {len(cookies)} 个 Cookie 到下载会话")
                return True
            else:
                self._log("ERROR", "登录失败！请检查用户名和密码，或页面结构已更改。")
                self._log("ERROR", f"当前URL: {current_url}")
                return False
        except Exception as e:
            self._log("ERROR", f"登录过程中出错: {e}")
            return False

    ## ----------------------------------------------------------------
    ## 核心下载与CSV日志 (线程安全)
    ## ----------------------------------------------------------------

    def log_result_to_csv(
        self,
        task_type,
        identifier,
        file_name,
        status,
        size_kb,
        url,
        elapsed_s,
        error="",
    ):
        """
        线程安全地记录下载日志到CSV文件。
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.log_lock:
            try:
                with open(self.log_file, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            timestamp,
                            task_type,
                            identifier,
                            file_name,
                            status,
                            f"{size_kb:.2f}",
                            url,
                            f"{elapsed_s:.2f}",
                            error,
                        ]
                    )
            except Exception as e:
                # 记录到控制台，避免日志失败导致程序崩溃
                self._log(f"CRITICAL: 写入CSV日志失败: {e}", "ERROR")

    def _download_file(self, task_type, identifier, url, save_path):
        """
        [线程工作函数] 下载单个文件并记录日志。
        如果文件已存在，则跳过并记录。
        """
        start_time = time.time()
        file_name = os.path.basename(save_path)

        try:
            # 1. 检查文件是否已存在
            if os.path.exists(save_path):
                size_kb = os.path.getsize(save_path) / 1024
                self.log_result_to_csv(
                    task_type, identifier, file_name, "exists", size_kb, url, 0
                )
                return True  # 已存在，视为成功

            # 2. 随机休眠 (轻度反爬)
            time.sleep(random.uniform(0.1, 0.5))

            # 3. 下载
            with self.session.get(url, stream=True, timeout=self.timeout) as response:
                response.raise_for_status()  # 如果状态码不是200，将触发重试或抛出异常

                with open(save_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            # 4. 记录成功
            size_kb = os.path.getsize(save_path) / 1024
            elapsed = time.time() - start_time
            self.log_result_to_csv(
                task_type, identifier, file_name, "success", size_kb, url, elapsed
            )
            return True

        except Exception as e:
            # 5. 记录失败
            elapsed = time.time() - start_time
            self.log_result_to_csv(
                task_type, identifier, file_name, "failed", 0, url, elapsed, str(e)
            )
            # 将异常抛出，以便tqdm循环可以捕获它
            raise e

    ## ----------------------------------------------------------------
    ## 任务1: 爬取图片库
    ## ----------------------------------------------------------------

    def submit_gallery_tasks(self, executor, save_dir, max_pages=None):
        """
        [Selenium 驱动] 遍历图片库页面，自动解析总页数，提交下载任务到线程池。
        返回 Future 列表。

        Args:
            executor: 线程池执行器。
            save_dir: 保存目录。
            max_pages (int, optional): 最大爬取页数。None表示爬取所有页。
        """
        self._log("INFO", "--- 开始任务 1: 爬取图片库 ---")
        os.makedirs(save_dir, exist_ok=True)

        # 访问第一页
        base_page_url = f"{self.base_url}images.php?p=1&pos=7&prot=4&race=0&pagina=1"
        self.driver.get(base_page_url)
        time.sleep(random.uniform(0.5, 1.5))

        # 解析总页数
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        pagination = soup.find("div", class_="pagination")
        total_pages = 1
        if pagination:
            page_numbers = []
            for li in pagination.find_all("li"):
                a = li.find("a")
                if a and "Next" not in a.get_text(strip=True):
                    m = re.search(r"pagina=(\d+)", a.get("href", ""))
                    if m:
                        page_numbers.append(int(m.group(1)))
            if page_numbers:
                total_pages = max(page_numbers)
        self._log("INFO", f"解析到图片库总页数: {total_pages}")

        # 根据 max_pages 确定要爬取的页数
        pages_to_scrape = total_pages
        if max_pages is not None:
            pages_to_scrape = min(total_pages, max_pages)
            self._log(
                "INFO",
                f"计划爬取 {pages_to_scrape} / {total_pages} 页 (上限: {max_pages})",
            )
        else:
            self._log("INFO", f"计划爬取 {pages_to_scrape} / {total_pages} 页 (无上限)")

        futures = []

        # 遍历每一页，使用 tqdm 进度条
        for page_num in tqdm(
            range(1, pages_to_scrape + 1), desc="[任务1] 爬取图片库页面"
        ):
            page_url = re.sub(r"pagina=\d+", f"pagina={page_num}", base_page_url)
            try:
                self.driver.get(page_url)
                time.sleep(random.uniform(0.5, 1.5))
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                imagem_divs = soup.find_all("div", class_="imagem")

                if not imagem_divs:
                    self._log("WARN", f"第 {page_num} 页未找到任何图片")
                    continue

                for div in imagem_divs:
                    a_tag = div.find(
                        "a",
                        href=re.compile(
                            r"\.(jpg|jpeg|png|bmp|gif|tif|tiff)$", re.IGNORECASE
                        ),
                    )
                    if not a_tag:
                        continue

                    href = a_tag.get("href")
                    if not href:
                        continue

                    img_url = urljoin(self.base_url, href.strip(" '\"\n"))
                    img_name = os.path.basename(urlparse(img_url).path)
                    save_path = os.path.join(save_dir, img_name)

                    # 提交下载任务
                    f = executor.submit(
                        self._download_file,
                        self.TASK_GALLERY,
                        f"Page_{page_num}",
                        img_url,
                        save_path,
                    )
                    futures.append(f)

            except Exception as e:
                self._log("ERROR", f"分析第 {page_num} 页失败: {e}")

            # 模拟翻页延迟
            time.sleep(random.uniform(*self.delay_range))

        self._log("SUCCESS", f"图片库任务提交完毕，共 {len(futures)} 个文件待下载。")
        return futures

    ## ----------------------------------------------------------------
    ## 任务2: 爬取患者数据
    ## ----------------------------------------------------------------

    def _navigate_to_patient_list(self):
        """[Selenium 驱动] 导航到患者列表页面"""
        try:
            self._log("INFO", "正在导航到患者列表...")
            # 尝试点击链接
            patient_list_links = self.driver.find_elements(
                By.XPATH,
                "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'patient') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'list')]",
            )

            if patient_list_links:
                patient_list_links[0].click()
                time.sleep(random.uniform(*self.delay_range))
                return True

            # 如果点击失败，尝试直接访问
            self._log("WARN", "未找到'Patient List'链接，尝试直接访问 patients.php")
            self.driver.get(f"{self.base_url}/patients.php")
            time.sleep(random.uniform(*self.delay_range))
            if "patients.php" in self.driver.current_url:
                return True

            return False
        except Exception as e:
            self._log("ERROR", f"导航到患者列表失败: {e}")
            return False

    def _extract_patient_list(self):
        """[Selenium 驱动] 提取所有页面的患者列表"""
        patients_all = []
        page = 1

        while True:
            self._log("INFO", f"正在解析患者列表第 {page} 页...")
            try:
                page_source = self.driver.page_source
                soup = BeautifulSoup(page_source, "html.parser")
                table = soup.find("table", id="mytable")
                if table is None:
                    self._log("WARN", "未找到 id='mytable' 的表格，列表解析终止。")
                    break

                headers = [th.get_text(strip=True) for th in table.find_all("th")]
                rows = []

                for tr in table.find_all("tr")[1:]:  # 跳过表头
                    cols = tr.find_all("td")
                    if not cols:
                        continue
                    row = [col.get_text(strip=True) for col in cols]
                    link = tr.find("a", href=re.compile(r"details\.php\?id="))
                    row.append(urljoin(self.base_url, link["href"]) if link else None)
                    rows.append(row)

                df = pd.DataFrame(rows, columns=headers + ["detail_url"])
                df["page"] = page
                patients_all.append(df)
                self._log("INFO", f"第 {page} 页提取到 {len(df)} 个患者记录")

                # --- 查找“下一页”按钮 ---
                next_link_elem = self.driver.find_elements(
                    By.XPATH, "//a[contains(text(), 'Next') or contains(text(), '»')]"
                )

                if next_link_elem:
                    self._log("INFO", "进入下一页...")
                    next_link_elem[0].click()
                    time.sleep(random.uniform(*self.delay_range))
                    page += 1
                else:
                    self._log("INFO", "没有更多页面，患者列表解析结束。")
                    break
            except Exception as e:
                self._log("ERROR", f"解析患者列表第 {page} 页失败: {e}")
                break

        if not patients_all:
            return pd.DataFrame()

        result = pd.concat(patients_all, ignore_index=True)
        self._log("SUCCESS", f"共提取到 {len(result)} 个患者信息（共 {page - 1} 页）")
        return result

    def _extract_patient_details(self, current_url):
        """[Selenium 驱动] 提取患者详情页面的结构化信息"""
        try:
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            details = {
                "page_url": current_url,
                "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "id": None,
                "name": None,
                "age": None,
                "register_date": None,
                "marital_status": None,
                "race": None,
                "diagnosis": None,
                "personal_history": None,
                "medical_history": None,
                "protocol_recommendations": None,
                "temperature": None,
                "files": [],
            }

            # 信息块
            info_div = soup.find("div", class_="descripcion1")
            if info_div:
                text = info_div.get_text(" ", strip=True)
                id_match = re.search(r"ID:\s*(\d+)", text)
                if id_match:
                    details["id"] = id_match.group(1)
                p_tags = info_div.find_all("p")
                if len(p_tags) >= 2:
                    details["name"] = p_tags[1].get_text(strip=True)
                age_match = re.search(r"(\d+)\s*years", text)
                if age_match:
                    details["age"] = int(age_match.group(1))
                reg_match = re.search(r"Registered at\s*([\d-]+)", text)
                if reg_match:
                    details["register_date"] = reg_match.group(1)
                mar_match = re.search(r"Marital status:\s*([\w\s]+)", text)
                if mar_match:
                    details["marital_status"] = mar_match.group(1).strip(". ")
                race_match = re.search(r"Race:\s*([\w\s]+)", text)
                if race_match:
                    details["race"] = race_match.group(1).strip(". ")

            # 诊断
            diag_p = soup.find("p", class_="view-diagnostico")
            if diag_p:
                span = diag_p.find("span")
                if span:
                    details["diagnosis"] = span.get_text(strip=True)

            # 其他描述
            mh_div = soup.find("div", class_="descripcion2")
            if mh_div:
                details["medical_history"] = mh_div.get_text(" ", strip=True)
            pr_div = soup.find("div", class_="descripcion3")
            if pr_div:
                details["protocol_recommendations"] = pr_div.get_text(" ", strip=True)
                temp_match = re.search(
                    r"Body temperature:\s*([\d.]+)", details["protocol_recommendations"]
                )
                if temp_match:
                    details["temperature"] = float(temp_match.group(1))

            # 文件链接
            for file_div in soup.find_all("div", class_="imagenspaciente"):
                for a in file_div.find_all("a", href=True):
                    file_name = os.path.basename(urlparse(a["href"]).path)
                    url = urljoin(self.base_url, a["href"])
                    file_type = (
                        "image"
                        if file_name.lower().endswith((".jpg", ".png"))
                        else "thermal_matrix"
                        if file_name.lower().endswith(".txt")
                        else "other"
                    )
                    details["files"].append(
                        {
                            "file_name": file_name,
                            "title": a.get("title", ""),
                            "url": url,
                            "type": file_type,
                        }
                    )
            return details
        except Exception as e:
            self._log("ERROR", f"提取患者详情失败 ({current_url}): {e}")
            return None  # 返回 None 以便上游跳过

    def _sanitize_filename(self, filename):
        """清理文件名，移除不安全字符"""
        return re.sub(r'[<>:"/\\|?*]', "_", filename)[:150]

    def submit_patient_tasks(self, executor, save_dir):
        """
        [Selenium 驱动] 遍历患者列表，[提交]下载任务到线程池。
        返回 Future 列表。
        """
        self._log("INFO", "--- 开始任务 2: 爬取患者数据 ---")

        # 创建子文件夹
        images_folder = os.path.join(save_dir, "images")
        thermal_folder = os.path.join(save_dir, "thermal_matrix")
        metadata_folder = os.path.join(save_dir, "metadata")
        os.makedirs(images_folder, exist_ok=True)
        os.makedirs(thermal_folder, exist_ok=True)
        os.makedirs(metadata_folder, exist_ok=True)

        futures = []
        all_patients_metadata = []  # 存储所有患者的JSON数据

        try:
            if not self._navigate_to_patient_list():
                self._log("ERROR", "无法导航到患者列表，任务2终止。")
                return []

            patients_df = self._extract_patient_list()
            if patients_df.empty:
                self._log("WARN", "未提取到任何患者信息，任务2终止。")
                return []

            total_patients = len(patients_df)
            for i, row in enumerate(patients_df.itertuples(index=False), 1):
                self._log(
                    "INFO",
                    f"--- [患者 {i}/{total_patients}] 正在处理: {row.Records} (ID: {row.ID}) ---",
                )

                if not row.detail_url:
                    self._log("WARN", f"患者 {row.ID} 没有详情URL，跳过。")
                    continue

                # 1. 访问详情页
                self.driver.get(row.detail_url)
                time.sleep(random.uniform(*self.delay_range))

                # 2. 提取详情
                patient_details = self._extract_patient_details(row.detail_url)
                if not patient_details:
                    self._log("ERROR", f"无法提取患者 {row.ID} 的详情，跳过。")
                    continue

                # 3. 合并信息 (将 DataFrame 的行转为 dict)
                patient_data = row._asdict()
                patient_data.update(patient_details)
                all_patients_metadata.append(patient_data)

                # 4. 保存元数据 (JSON)
                json_filename = self._sanitize_filename(
                    f"Patient_{row.ID}_{row.Records}.json"
                )
                json_path = os.path.join(metadata_folder, json_filename)
                try:
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(patient_data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    self._log("ERROR", f"保存JSON失败: {json_path} | {e}")

                # 5. 提交文件下载任务
                patient_id = patient_details.get("id", row.ID)
                for file_info in patient_details.get("files", []):
                    url = file_info["url"]
                    file_name = file_info["file_name"]

                    if file_info["type"] == "thermal_matrix":
                        save_path = os.path.join(thermal_folder, file_name)
                    elif file_info["type"] == "image":
                        save_path = os.path.join(images_folder, file_name)
                    else:
                        continue  # 跳过 'other' 类型

                    f = executor.submit(
                        self._download_file,
                        self.TASK_PATIENT,
                        f"Patient_{patient_id}",
                        url,
                        save_path,
                    )
                    futures.append(f)

            # 循环结束后，保存一个包含所有患者信息的总JSON文件
            all_json_path = os.path.join(save_dir, "all_patients_metadata.json")
            with open(all_json_path, "w", encoding="utf-8") as f:
                json.dump(all_patients_metadata, f, ensure_ascii=False, indent=2)
            self._log("SUCCESS", f"所有患者元数据已保存到: {all_json_path}")

        except Exception as e:
            self._log("ERROR", f"爬取患者数据时发生严重错误: {e}")
            self._log("ERROR", traceback.format_exc())

        self._log("SUCCESS", f"患者数据任务提交完毕，共 {len(futures)} 个文件待下载。")
        return futures

    ## ----------------------------------------------------------------
    ## 主运行方法
    ## ----------------------------------------------------------------

    def run(
        self,
        # --- 任务开关 ---
        scrape_gallery_images=True,
        scrape_patient_details=True,
        # --- 任务1 (Gallery) 配置 ---
        gallery_max_pages=None,
        gallery_save_dir="Thermography_imgs",
        # --- 任务2 (Patient) 配置 ---
        patient_save_dir="Patient_Data",
        # --- 并发配置 ---
        max_workers=10,
    ):
        """
        运行爬虫主流程

        Args:
            scrape_gallery_images (bool): 是否执行任务1
            scrape_patient_details (bool): 是否执行任务2
            gallery_max_pages (int, optional): 任务1要爬取的最大页数。
                                            None (默认) 表示爬取所有自动检测到的页面。
            gallery_save_dir (str): 任务1的保存目录
            patient_save_dir (str): 任务2的保存目录
            max_workers (int): 下载线程池的最大线程数
        """

        start_time = time.time()
        self._log("INFO", "--- 爬虫启动 ---")

        if not self.setup_driver() or not self.login():
            self._log("ERROR", "初始化或登录失败，程序退出。")
            if self.driver:
                self.driver.quit()
            return

        all_futures = []

        try:
            # --- 1. 任务提交阶段 ---
            # Selenium 在主线程中按顺序执行，将下载任务提交到线程池
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                if scrape_gallery_images:
                    gallery_futures = self.submit_gallery_tasks(
                        executor, gallery_save_dir, max_pages=gallery_max_pages
                    )
                    all_futures.extend(gallery_futures)

                if scrape_patient_details:
                    patient_futures = self.submit_patient_tasks(
                        executor, patient_save_dir
                    )
                    all_futures.extend(patient_futures)

                if not all_futures:
                    self._log(
                        "WARN", "没有选择任何任务，或者未发现任何可下载文件。程序退出。"
                    )
                    return

                # --- 2. 任务监控阶段 ---
                # 使用tqdm监控已提交任务的完成进度
                self._log(
                    "INFO", f"--- 开始多线程下载，共 {len(all_futures)} 个任务 ---"
                )

                success_count = 0
                failed_count = 0

                for future in tqdm(
                    concurrent.futures.as_completed(all_futures),
                    total=len(all_futures),
                    desc="[全局] 下载文件",
                ):
                    try:
                        result = future.result()  # 获取任务结果
                        if result:  # _download_file 返回 True (成功或已存在)
                            success_count += 1
                    except Exception as e:
                        # 捕获 _download_file 中抛出的异常
                        failed_count += 1
                        # (CSV日志已在 _download_file 中记录)
                        self._log("ERROR", f"一个下载任务失败: {e}")
                        # self._log("DEBUG", traceback.format_exc()) # 取消注释以获取详细堆栈

            self._log("SUCCESS", "--- 所有任务执行完毕 ---")
            self._log("INFO", f"总计成功 (含已存在): {success_count}")
            self._log("INFO", f"总计失败: {failed_count}")

        except Exception as e:
            self._log("ERROR", f"发生未捕获的严重错误: {e}")
            self._log("ERROR", traceback.format_exc())

        finally:
            # --- 3. 清理阶段 ---
            if self.driver:
                self.driver.quit()
                self._log("INFO", "浏览器已关闭")

        end_time = time.time()
        self._log("INFO", f"总耗时: {end_time - start_time:.2f} 秒")


# ----------------------
# 使用示例
# ----------------------
if __name__ == "__main__":
    # ---------------------------------
    # 请在此处填写您的凭据
    # ---------------------------------

    load_dotenv()
    USERNAME = os.getenv("USERNAME")
    PASSWORD = os.getenv("PASSWORD")

    # ---------------------------------
    # [可选] 请在此处填写您的chromedriver路径
    # ---------------------------------
    # 如果 chromedriver 已在您的系统 PATH 中, 可以忽略 driver_path 参数
    # 否则，请指定完整路径
    DRIVER_PATH = "/usr/local/bin/chromedriver"

    print("--- 爬虫配置 ---")
    print(f"用户名: {USERNAME}")
    print(f"驱动路径: {DRIVER_PATH}")
    print("-----------------")

    spider = ThermoMastoCrawler(USERNAME, PASSWORD, driver_path=DRIVER_PATH)

    # --- 灵活选择要运行的任务 ---
    spider.run(
        # --- 任务开关 ---
        scrape_gallery_images=True,  # 设置为 True 来爬取图片库
        scrape_patient_details=True,  # 设置为 True 来爬取患者数据
        # --- 任务1配置 ---
        gallery_max_pages=2,  # 爬取图片库的最大页数 (例如 2 用于测试, None 表示全部)
        gallery_save_dir="downloads/Thermography_imgs",  # 图片库保存位置
        # --- 任务2配置 ---
        patient_save_dir="downloads/Patient_Data",  # 患者数据保存位置
        # --- 性能配置 ---
        max_workers=8,  # 下载线程数 (根据您的网络调整)
    )
