# ThermoMastoCrawler

**ThermoMastoCrawler** 是一个面向 **[UFF Visual DMI 数据库](https://visual.ic.uff.br/dmi/)** 的数据采集工具，主要用于爬取乳腺疾病研究中的热成像图像及配套临床记录。项目集成了 Selenium、Requests及多线程机制，实现了结构化医学数据的自动化收集与整理。

## 核心功能

* **双重任务**：

  1. **任务1（Gallery）**：爬取公共图片库 (Database of mastologic images) 中的所有热成像图片。
  2. **任务2（Patient）**：访问每个患者的详情页面，获取个人信息、元数据以及相关图片和热矩阵文件。

* **健壮性设计**：

  * **会话共享**：Selenium 登录后，将 Cookie 同步到 Requests 会话，实现高速下载。
  * **自动重试**：Requests 会话配置 HTTP(S) 适配器，对 500、502、503、504 等网络错误自动重试。
  * **反爬策略**：支持随机 User-Agent、随机延迟及禁用 SSL 警告，模拟人类操作行为。
  * **断点续传**：下载前检查文件是否存在，已下载文件自动跳过，便于中断后恢复。

* **详细日志**：

  * 所有下载操作（成功、失败、已存在）都会记录到 `download_log_unified.csv`。
  * 日志系统使用线程锁设计，确保多线程环境下写入安全。

* **数据结构化**：

  * 患者数据保存在 `Patient_Data` 文件夹下，包含三个子目录：
    * `images`：存放图片
    * `thermal_matrix`：存放 `.txt` 热矩阵文件
    * `metadata`：存放每位患者的 JSON 元数据
  * 同时生成 `all_patients_metadata.json`，汇总所有患者元数据。

---

## 使用方法

### 配置环境

```bash
git clone https://github.com/shujuecn/ThermoMastoCrawler.git
cd ThermoMastoCrawler
pip install -r requirements.txt
```

---

### 下载并配置 Web Driver

1. 检查您的 Chrome 浏览器版本。
2. 下载与浏览器版本匹配的 [chromedriver](https://chromedriver.chromium.org/downloads)。
3. 配置驱动路径：

   * **方式一（推荐）**：将 chromedriver 可执行文件放入系统 PATH，如 `/usr/local/bin` 或 `/usr/bin`。
   * **方式二（修改代码）**：在爬虫脚本底部的代码块中，将 `DRIVER_PATH` 指向 chromedriver 的绝对路径。

---

### 设置登录凭据

在项目根目录创建 `.env` 文件，输入您的用户名和密码：

```text
USERNAME=your_username_here
PASSWORD=your_password_here
```

---

### 启动程序

确认环境和驱动配置完成后，运行 Python 脚本：

```bash
python main.py
```

程序会自动读取 `.env` 中的凭据，初始化 Selenium 驱动并登录，然后根据配置开始爬取。

---

## 可调参数

在脚本末尾代码块中，可以通过 `spider.run()` 方法灵活配置：

```python
spider.run(
    # --- 任务开关 ---
    scrape_gallery_images=True,       # 是否执行任务1（爬取公共图片库）
    scrape_patient_details=True,      # 是否执行任务2（爬取患者详情）

    # --- 任务1 (Gallery) 配置 ---
    gallery_max_pages=2,              # 最大爬取页数，设为 None 表示全部
    gallery_save_dir="downloads/Thermography_imgs",

    # --- 任务2 (Patient) 配置 ---
    patient_save_dir="downloads/Patient_Data",

    # --- 性能配置 ---
    max_workers=8,                    # 下载线程数，可根据网络情况调整
)
```

---

## 数据使用与隐私声明

本项目仅供科研、教学和个人学习用途，不得用于任何商业或临床决策目的。

* 数据来源：所有数据均来自 [Universidade Federal Fluminense (UFF) Visual DMI](https://visual.ic.uff.br/dmi/) 官方公开数据库（经原网站授权访问）。
* 隐私合规：项目未采集、保存或传播任何可识别的个人身份信息。
* 使用责任：用户须遵守原数据源网站的访问协议与伦理声明，自行确保下载与使用行为的合法性。
* 推荐做法：下载完成后请本地使用，不建议二次分发或在线共享原始影像文件。

---

## 致谢

* 感谢 [YINys](https://github.com/yysti) 提供本项目的初始代码，为后续开发与完善奠定了基础。
* 感谢 [Universidade Federal Fluminense (UFF) Visual DMI](https://visual.ic.uff.br/dmi/) 项目组提供宝贵的医学影像数据。
