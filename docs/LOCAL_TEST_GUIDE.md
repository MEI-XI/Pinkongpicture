# 本地试用说明

当前版本用于单台 Windows 电脑试用。图片、数据库、产品资料、修改历史和区域样本保存在本机。手机照片先传到电脑再导入。

## 在这台电脑启动

项目已建立 `.venv`，CPU 模型已准备。打开 PowerShell：

```powershell
cd D:\DOME\picture
.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

用浏览器打开 <http://127.0.0.1:8000>。按 `Ctrl+C` 停止服务；待正在进行的识别结束后退出。下次按同样命令启动即可继续查看已保存记录。

只监听本机，不需要企业服务器、登录账号或 GPU。操作人姓名由使用者填写，不是身份认证。

## 在另一台电脑安装

需要 64 位 Python 3.12 或 3.13，推荐 3.12。不要使用全局 Python 3.15 安装这组 OCR 依赖。

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install -e . --no-deps
.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

首次识别会下载官方 PP-OCRv5 mobile 检测与识别模型到 `models/paddlex`。之后复用本地模型。也可将已下载完整的 `models` 目录复制到另一台测试电脑。应用不把包装图片发送给外部 OCR 服务。

已安装并测试的核心版本为 Python 3.12.14、PaddlePaddle 3.3.0、PaddleOCR 3.7.0、PaddleX 3.7.2。完整依赖见 `requirements.lock`。当前 Windows 环境启用 oneDNN 会产生 PIR 属性转换错误，因此关闭该加速配置。

## 完成一条来料记录

1. 填写右上角操作人姓名，导入 JPG、PNG、WebP 或 BMP 图片。单张最多 30 MB、4000 万像素。HEIC 先转换为 JPG。
2. 等待逐图识别。失败图可以重试，也可补拍或依据可核实资料补填。
3. 勾选同一个产品、同一批号的照片，建立来料记录。批量照片可以使用“建议分组”。
4. 对照原图核对七个字段。点选候选或文字区域可以查看、关联图片依据。多个候选需要人工选择。
5. 查找历史产品，与本次信息对照后选择已有档案或新建。规格、名称或生产厂商不同不能关联成同一产品；地址变化须明确同意增加版本。
6. 勾选已核对照片归属，再确认保存。记录首次确认时间使用固定北京时间，后续修改不改变它。

同产品同批号再次来料仍建立新记录。自动建议只在同一次上传的照片内合并，分次补拍的照片通过人工归组并入已有记录。缺少关键身份或批号线索时，照片留在待分组区。

移动照片必须填写可核实的归组依据。移动会使受影响记录重新进入待核对状态，移出照片所支撑的字段依据会被清除。保存前再次检查组内字段。

## 字段来源与日期

- 图片文字：选择当前组的具体文字区域。识别分数仅作复核提示。
- 资料补填：填写送货单编号、核实资料或其他明确来源，不作为原图训练标签。
- 未标注：说明检查了哪些包装位置、为何确定未标注。看不清不能直接当作未标注。

生产日期保留确认后的原文，仅将明确日期统一成 `YYYY-MM-DD`。含糊日期不猜测，位置提示如“见封口”需要补拍或核实资料。原始 OCR 输出仍保存在图片文字记录中；修正日期后，导出的原文不能再使用旧的误读日期。

已确认记录可以修改。填写原因及资料来源，保存草稿或重新确认。修改人、时间及前后内容保存在历史中。存在未确认修改时，导出仍使用上一次确认内容，并显示提醒。以前下载的 Excel 不会改变。

## 配置已有 Excel 模板

进入“记录与导出”，上传你实际使用的 `.xlsx` 模板，并明确：

- 工作表名称、数据起始行与结束行。
- 九个字段各自的列字母。每个字段须使用不同的列。
- 日期输出原文还是统一格式；未标注单元格是否同时写原因。

目标数据区域应为空白，不应包含示例数据、合并单元格或汇总行。程序保留表头，复制首个数据行的样式，按行平移该行未映射列的公式。每次导出建立一个新文件，不覆盖模板或旧导出文件。

当前适配器针对普通行列表格。旧版 `.xls`、宏、复杂图表对象、动态表格和特殊打印版式需要另行验证。实际模板尚未提供，因此不能视为已完成你现有模板的适配。首轮务必用 Excel 或日常办公软件打开结果，逐列核对位置、前导零、单位、公式与打印版式。

可按首次录入日期、产品档案和批号筛选。未确认的新记录不进入 Excel。

## 产品记忆与样本

确认结果保存到产品档案，下次可查找历史候选并对照。第一版不会自动训练模型，也不会用上次批号或日期替代本次识别。

要积累 OCR 纠错样本，在字段的图片依据旁校对该文字区域的完整文字，包含区域内的字段标签。确认时自动保存区域截图和正确文字。多行地址要分别对应各个区域，不能把整个地址贴给单独一行。

资料补填不生成图片标签。重新确认记录会停用旧版本样本，避免相互矛盾的标签同时有效。若样本生成失败，界面分别报告业务记录保存结果和样本错误。

## 数据位置与保存

| 位置 | 内容 |
| --- | --- |
| `data/records.sqlite3` | 来料记录、产品版本、修改历史、图片信息及设置 |
| `data/images/` | 矫正手机方向后的本地图像副本；不修改用户源文件 |
| `data/samples/` | 已校对文字区域截图 |
| `data/templates/` | 导入的 Excel 模板 |
| `data/exports/` | 每次生成的 Excel |
| `models/paddlex/` | 本机 OCR 模型 |

需要备份时，停止服务后复制整个 `data` 目录。不要只复制数据库而遗漏图片和区域截图。上述目录均被 Git 忽略。

可以在启动前设置 `PINKONG_DATA_DIR` 指向另一处本地数据目录。开发浏览器测试使用 `.cache/browser-test-data`，不会把测试记录混入默认 `data`。

## 开发验证

常规测试使用真实 SQLite、图片文件和工作簿，仅替换耗时的外部 OCR 引擎。

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check app tests
.venv\Scripts\python.exe -m ruff format --check app tests
```

真实模型测试单独运行，默认在普通测试中跳过：

```powershell
$env:RUN_REAL_OCR = '1'
.venv\Scripts\python.exe -m pytest tests/test_real_ocr.py -s --basetemp=.cache/pytest-models
Remove-Item Env:RUN_REAL_OCR
```

这组测试使用 Windows 字体生成中文标签，比较 mobile 与 server 配置。不要同时运行使用同一个 `--basetemp` 的两个测试进程。真实模型测试通过也不能替代真实包装试用。

浏览器测试额外需要 Node.js 和 Microsoft Edge；应用本身不需要 Node.js。先运行 `npm ci`，用单独的 PowerShell 启动测试服务，再运行测试：

```powershell
$env:PINKONG_DATA_DIR = (Join-Path $PWD '.cache/browser-test-data')
.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765
```

```powershell
npm run test:browser
```

## 真实试用仍需的材料

提供首批包装照片、七字段核实答案，以及固定 Excel 模板和填写示例。建议覆盖同款不同批号、缺少批号的背面、小字反光、多行地址、委托方与生产商并列。另留一部分未调试照片验收。

试用时记录七字段全对率、各字段正确率、错误合并与待分组比例、人工改动数、每条复核时间和识别耗时。当前没有真实包装准确率或多人容量承诺。
