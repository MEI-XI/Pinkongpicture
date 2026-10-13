const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function saveWithDelayedResponse(page, buttonName, pattern) {
  let release, arrived, finished;
  const gate = new Promise(resolve => { release = resolve; });
  const responseReady = new Promise(resolve => { arrived = resolve; });
  const responseSent = new Promise(resolve => { finished = resolve; });
  const handler = async route => {
    try {
      const response = await route.fetch(); // Delay the real server response, without changing its contents.
      arrived();
      await gate;
      await route.fulfill({response});
    } finally { finished(); }
  };
  await page.route(pattern, handler);
  try {
    await page.getByRole('button', {name:buttonName, exact:true}).click();
    await responseReady;
    assert.equal(await page.getByLabel('批号确认值', {exact:true}).isDisabled(), true,
      'Fields must not accept edits that a pending save response would overwrite');
    assert.equal(await page.getByLabel('操作人', {exact:true}).isDisabled(), true);
    assert.equal(await page.getByRole('button', {name:'保存草稿', exact:true}).isDisabled(), true);
    assert.equal(await page.getByRole('button', {name:'确认并保存记录', exact:true}).isDisabled(), true);
  } finally {
    release();
    await responseSent;
    await page.unroute(pattern, handler);
  }
}

// Browser workflow seam: use a disposable real local service, never the user's data directory.
// Run after launching the app on a test data directory. No API responses are mocked.
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1512, height: 982 } });
  page.setDefaultTimeout(10000);
  const name = `流程样品-${Date.now()}`;
  const imageName = `${name}.png`;
  try {
    await page.goto(process.env.TEST_BASE_URL || 'http://127.0.0.1:8765');
    await page.getByLabel('导入包装照片').setInputFiles({ name: imageName, mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jJ1sAAAAASUVORK5CYII=', 'base64') });
    const photo = page.getByRole('checkbox', { name: `选择照片 ${imageName}` });
    await photo.waitFor();
    await photo.check();
    await page.getByRole('button', { name: '选中照片新建记录', exact: true }).click();
    const values = { name, specification: '25kg/袋', manufacturer: '测试原料厂', address: '测试市工业路8号', lot: '0012', production_date: '2026-10-01', shelf_life: '12个月' };
    const labels = { name: '产品名称', specification: '规格', manufacturer: '生产厂商', address: '生产地址', lot: '批号', production_date: '生产日期', shelf_life: '保质期' };
    for (const [key, value] of Object.entries(values)) {
      await page.getByLabel(`${labels[key]}来源`, { exact: true }).selectOption('external');
      await page.getByLabel(`${labels[key]}确认值`, { exact: true }).fill(value);
      await page.getByLabel(`${labels[key]}说明或资料来源`, { exact: true }).fill('依据测试送货单核实');
    }
    await page.getByLabel('操作人', { exact: true }).fill('浏览器测试员');
    await page.getByLabel('已检查本组照片属于同一产品、同一批号').check();
    await saveWithDelayedResponse(page, '确认并保存记录', '**/api/receipts/*/confirm');
    await page.getByRole('status').filter({ hasText: '已确认保存' }).waitFor();
    await page.getByRole('button', { name: '记录与导出', exact: true }).click();
    const row = page.getByRole('row').filter({ hasText: name });
    await row.waitFor();
    assert.match(await row.innerText(), /0012/);
    assert.match(await row.innerText(), /浏览器测试员/);
    await page.screenshot({ path: '.cache/browser-records.png', fullPage: true });
    console.log('PASS: imported image → manually grouped → sourced seven fields → human confirmation → visible record');
    const python = process.env.TEST_PYTHON || '.venv/Scripts/python.exe';
    const template = execFileSync(python, ['-c', "from openpyxl import Workbook; from openpyxl.styles import Font; from io import BytesIO; import sys; b=Workbook(); s=b.active; s.title='来料表'; s.append(['产品名称','规格','生产厂商','生产地址','批号','生产日期','保质期','录入时间','操作人']); s['A1'].font=Font(bold=True); output=BytesIO(); b.save(output); sys.stdout.buffer.write(output.getvalue())"]);
    await page.getByLabel('上传 Excel 模板', {exact:true}).setInputFiles({name:'浏览器测试模板.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:template});
    await page.getByLabel('工作表', {exact:true}).selectOption('来料表');
    for (const [index,label] of [...Object.values(labels),'录入时间','操作人'].entries()) await page.getByLabel(`${label}列`, {exact:true}).fill(String.fromCharCode(65+index));
    await page.getByRole('button',{name:'保存模板映射',exact:true}).click();
    await page.getByText('映射已保存', {exact:true}).waitFor();
    const productOption = page.getByRole('option').filter({hasText:name});
    await page.getByLabel('产品档案', {exact:true}).selectOption(await productOption.getAttribute('value'));
    await page.getByRole('button',{name:'筛选',exact:true}).click();
    await page.getByRole('button',{name:'导出 Excel',exact:true}).click();
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('link',{name:'下载 Excel（1 条记录）',exact:true}).click();
    const download = await downloadEvent;
    await download.saveAs('.cache/browser-export.xlsx');
    const exported = JSON.parse(execFileSync(python,['-c',"from openpyxl import load_workbook; import json; b=load_workbook('.cache/browser-export.xlsx'); s=b['来料表']; print(json.dumps({'name':s['A2'].value,'lot':s['E2'].value,'operator':s['I2'].value,'bold':s['A1'].font.bold}))"],{encoding:'utf8'}));
    assert.deepEqual(exported,{name,lot:'0012',operator:'浏览器测试员',bold:true});
    console.log('PASS: upload actual xlsx → map nine columns → select product → download → verify Excel cells and header format');
    await row.getByRole('button',{name:'查看 / 修改',exact:true}).click();
    await page.getByLabel('批号确认值',{exact:true}).fill('0099');
    await page.getByLabel('修改原因与资料来源',{exact:true}).fill('测试送货单更正批号');
    await saveWithDelayedResponse(page, '保存草稿', /\/api\/receipts\/[^/]+$/);
    await page.getByRole('status').filter({hasText:'草稿已保存'}).waitFor();
    await page.getByRole('button',{name:'记录与导出',exact:true}).click();
    assert.match(await row.innerText(), /0012/);
    assert.match(await row.innerText(), /修改待确认/);
    await row.getByRole('button',{name:'查看 / 修改',exact:true}).click();
    assert.equal(await page.getByLabel('批号确认值',{exact:true}).inputValue(),'0099');
    await page.getByLabel('修改原因与资料来源',{exact:true}).fill('测试送货单更正批号，复核完成');
    await page.getByRole('button',{name:'确认并保存记录',exact:true}).click();
    await page.getByRole('status').filter({hasText:'已确认保存'}).waitFor();
    await page.getByText('查看确认与修改历史',{exact:true}).click();
    await page.getByText('确认版本 2 · 浏览器测试员',{exact:true}).waitFor();
    await page.getByRole('button',{name:'记录与导出',exact:true}).click();
    assert.match(await row.innerText(),/0099/);
    console.log('PASS: saved correction stays pending → prior confirmed record remains visible → reconfirm retains two historical revisions');
    await page.getByRole('button',{name:'图片复核',exact:true}).click();
    const ocrImageName=`文字样品-${Date.now()}.png`;
    const ocrImage=execFileSync(python,['-c',"from PIL import Image,ImageDraw,ImageFont; from io import BytesIO; import os,sys; im=Image.new('RGB',(1100,760),'white'); d=ImageDraw.Draw(im); font=ImageFont.truetype(os.environ.get('TEST_FONT','C:/Windows/Fonts/msyh.ttc'),42); lines=['产品名称：葡萄糖','规格：25kg','生产厂商：测试原料厂','生产地址：测试市工业路8号','批号：0012','生产日期：2026年10月1日','保质期：12个月']; [d.text((40,35+i*100),line,font=font,fill='black') for i,line in enumerate(lines)]; out=BytesIO(); im.save(out,format='PNG'); sys.stdout.buffer.write(out.getvalue())"]);
    await page.getByLabel('导入包装照片').setInputFiles({name:ocrImageName,mimeType:'image/png',buffer:ocrImage});
    const ocrPhoto=page.locator('.photo-row').filter({has:page.getByRole('checkbox',{name:`选择照片 ${ocrImageName}`})});
    await ocrPhoto.getByText(/处文字/).waitFor({timeout:120000});
    await ocrPhoto.getByRole('checkbox').check();
    await page.getByRole('button',{name:'建议分组',exact:true}).click();
    await page.getByRole('button',{name:'应用建议并建立记录',exact:true}).click();
    await page.getByRole('status').filter({hasText:'已建立 1 个建议图片组'}).waitFor();
    await page.getByLabel('产品名称确认值',{exact:true}).waitFor();
    assert.equal(await page.getByLabel('产品名称确认值',{exact:true}).inputValue(),'葡萄糖');
    const nameGroup=page.getByRole('group',{name:'产品名称核对',exact:true});
    await nameGroup.getByText('原文、来源与文字依据',{exact:true}).click();
    await nameGroup.getByLabel(/^文字区域校对 /).fill('产品名称：葡萄糖');
    await page.getByLabel('已检查本组照片属于同一产品、同一批号').check();
    await page.getByRole('button',{name:'确认并保存记录',exact:true}).click();
    await page.getByRole('status').filter({hasText:'保存 1 个纠错样本'}).waitFor();
    await page.screenshot({path:'.cache/browser-workbench.png',fullPage:true});
    console.log('PASS: real PaddleOCR → suggested grouping → extracted seven fields → region evidence correction → confirmed sample');
    await page.getByRole('button',{name:`移动照片 ${ocrImageName}`,exact:true}).click();
    await page.getByLabel('照片归属',{exact:true}).selectOption('');
    await page.getByLabel('归组依据',{exact:true}).fill('测试复核：将照片暂退回待分组区');
    await page.getByRole('button',{name:'保存照片归属',exact:true}).click();
    await page.getByRole('status').filter({hasText:'图片归属已调整'}).waitFor();
    assert.equal(await page.getByLabel('已检查本组照片属于同一产品、同一批号').isChecked(),false);
    assert.equal(await page.getByLabel('产品名称确认值',{exact:true}).inputValue(),'');
    const movedPhoto=page.locator('.photo-row').filter({has:page.getByRole('checkbox',{name:`选择照片 ${ocrImageName}`})});
    await movedPhoto.dragTo(page.locator('.group-card.selected'));
    await page.getByLabel('归组依据',{exact:true}).fill('已对照完整包装核实产品及批号，归回原来料记录');
    await page.getByRole('button',{name:'保存照片归属',exact:true}).click();
    await page.getByRole('status').filter({hasText:'图片归属已调整'}).waitFor();
    await page.getByLabel('产品名称确认值',{exact:true}).fill('葡萄糖');
    assert.equal(await page.getByLabel('已检查本组照片属于同一产品、同一批号').isChecked(),false);
    console.log('PASS: sourced manual move removes stale evidence → drag regroup requires renewed human confirmation');
    await nameGroup.getByText('原文、来源与文字依据',{exact:true}).click();
    await nameGroup.getByLabel(/^文字区域校对 /).fill('产品名称：葡萄糖');
    await page.getByLabel('已检查本组照片属于同一产品、同一批号').check();
    await page.getByLabel('修改原因与资料来源',{exact:true}).fill('归组核实后保存区域校对草稿');
    await page.getByRole('button',{name:'保存草稿',exact:true}).click();
    await page.getByRole('status').filter({hasText:'草稿已保存'}).waitFor();
    await page.reload();
    await page.locator('.group-select').first().click();
    await nameGroup.getByText('原文、来源与文字依据',{exact:true}).click();
    assert.equal(await nameGroup.getByLabel(/^文字区域校对 /).inputValue(),'产品名称：葡萄糖');
    assert.equal(await page.getByLabel('已检查本组照片属于同一产品、同一批号').isChecked(),true);
    assert.notEqual(await page.locator('input[name="product-choice"]:checked').inputValue(),'new');
    console.log('PASS: saved draft restores regional text, grouping review and linked product after page reload');
    await page.getByLabel('产品名称确认值',{exact:true}).fill('无水葡萄糖');
    assert.equal(await nameGroup.getByLabel(/^文字区域校对 /).inputValue(),'');
    await page.getByLabel('产品名称确认值',{exact:true}).fill('葡萄糖');
    await page.getByLabel('修改原因与资料来源',{exact:true}).fill('重新检查字段，旧区域标签已失效');
    await page.getByRole('button',{name:'保存草稿',exact:true}).click();
    await page.getByRole('status').filter({hasText:'草稿已保存'}).waitFor();
    await nameGroup.getByText('原文、来源与文字依据',{exact:true}).click();
    assert.equal(await nameGroup.getByLabel(/^文字区域校对 /).inputValue(),'');
    console.log('PASS: business correction clears stale region labels, including after draft reload');
    const voidProduct=await page.locator('input[name="product-choice"]:checked').inputValue();
    await page.getByRole('button',{name:`移动照片 ${ocrImageName}`,exact:true}).click();
    await page.getByLabel('照片归属',{exact:true}).selectOption('');
    await page.getByLabel('归组依据',{exact:true}).fill('核实重复登记，先移出照片再作废空记录');
    await page.getByRole('button',{name:'保存照片归属',exact:true}).click();
    await page.getByRole('status').filter({hasText:'图片归属已调整'}).waitFor();
    await page.getByRole('button',{name:'作废空记录',exact:true}).click();
    await page.getByLabel('作废原因',{exact:true}).fill('核实为重复登记，保留历史并排除导出');
    await page.getByRole('button',{name:'确认作废',exact:true}).click();
    await page.getByRole('status').filter({hasText:'空记录已作废'}).waitFor();
    await page.locator('.group-card.selected').getByText('已作废',{exact:true}).waitFor();
    await page.getByText('查看确认与修改历史',{exact:true}).click();
    await page.getByText('作废记录 · 浏览器测试员',{exact:true}).waitFor();
    await page.getByRole('button',{name:'记录与导出',exact:true}).click();
    await page.getByLabel('产品档案',{exact:true}).selectOption(voidProduct);
    await page.getByRole('button',{name:'筛选',exact:true}).click();
    await page.getByText('还没有符合条件的确认记录',{exact:true}).waitFor();
    await page.getByRole('button',{name:'清除',exact:true}).click();
    await row.getByRole('button',{name:'查看 / 修改',exact:true}).click();
    await page.getByLabel('批号确认值',{exact:true}).waitFor({state:'visible'});
    assert.equal(await page.getByLabel('批号确认值',{exact:true}).isDisabled(),false);
    assert.equal(await page.getByRole('button',{name:'保存草稿',exact:true}).isDisabled(),false);
    console.log('PASS: explicit void retains audit history and excludes empty duplicate from confirmed records');
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'.cache/browser-mobile.png',fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  } catch(error) { console.error(error); await page.screenshot({path:'.cache/browser-failure.png',fullPage:true}); console.error('Visible error:', await page.locator('#error').textContent()); throw error; }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
