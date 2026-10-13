'use strict';
const FIELDS = {name:'产品名称',specification:'规格',manufacturer:'生产厂商',address:'生产地址',lot:'批号',production_date:'生产日期',shelf_life:'保质期'};
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = {images:[],receipts:[],products:[],samples:[]};
let selectedReceipt = null, selectedImage = null, activeField = null, fieldValues = {}, candidates = {}, loadedVersion = 0, dirty = false, zoom = 1;
let selectedPhotos = new Set(), regionLabels = {}, productDecision = {mode:'new'}, filter = {}, refreshQueue = Promise.resolve(), templateLoaded = null, dragging = false;
let saving = false, reviewedRegions = new Set();
const imageUrl = id => `/api/images/${encodeURIComponent(id)}/file`;
const currentReceipt = () => state.receipts.find(row => row.id === selectedReceipt);
const blankField = () => ({value:'',raw:'',source:'image',note:'',refs:[]});

async function api(path, options={}) {
  const response = await fetch(path, options.body instanceof FormData ? options : {...options, headers:{'Content-Type':'application/json',...options.headers}, body:options.body === undefined ? undefined : JSON.stringify(options.body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请检查输入并重试。');
  return data;
}
function message(text, error=false) { const box = $(error?'#error':'#notice'); box.textContent=text; box.hidden=false; if(!error) $('#error').hidden=true; }
async function action(button, callback) { if(button) button.disabled=true; $('#notice').hidden=true;try {await callback();} catch(error){message(error.message,true);} finally {if(button) button.disabled=false;} }
function setDirty() {dirty=true; $('#draft-status').textContent='有尚未保存的修改。';}
function invalidateLabels(key) {
  for(const ref of fieldValues[key]?.refs || []) {
    delete regionLabels[ref]; reviewedRegions.delete(ref);
    $$('[data-region]').filter(input=>input.dataset.region===ref).forEach(input=>{input.value='';});
  }
  $('#draft-status').textContent='字段已更正，相关文字区域需重新校对后才能积累样本。';
}
async function saveRecord(confirm) {
  if(saving)return;
  const identifier=selectedReceipt, body=structuredClone(recordBody());
  const controls=$$('button,input,select,textarea').map(element=>[element,element.disabled]);
  saving=true; controls.forEach(([element])=>{element.disabled=true;});
  $('main').inert=true; $('.app-header').inert=true;
  message('正在保存，请稍候…');
  try {
    const result=await api(`/api/receipts/${identifier}${confirm?'/confirm':''}`,{method:confirm?'POST':'PUT',body});
    dirty=false; await refresh(); await selectReceipt(identifier,true);
    if(confirm) {
      message(`已确认保存。${result.samples.count?`保存 ${result.samples.count} 个纠错样本。`:''}`);
      if(result.samples.status==='error')message(`记录已保存，但样本保存失败：${result.samples.error}`,true);
    } else {
      $('#draft-status').textContent='草稿已保存，仍需人工确认。';
      message('草稿已保存。修改需重新确认后才会用于导出。');
    }
  } finally {
    controls.forEach(([element,disabled])=>{element.disabled=disabled;});
    $('main').inert=false; $('.app-header').inert=false; saving=false; renderQueue();
  }
}
function showPage(name) { $$('[data-page]').forEach(button=>{button.classList.toggle('active',button.dataset.page===name); if(button.dataset.page===name) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');}); $('#page-workbench').hidden=name!=='workbench'; $('#page-records').hidden=name!=='records'; if(name==='records') renderRecords(); }

function refresh() {
  refreshQueue=refreshQueue.then(loadState,loadState);
  return refreshQueue;
}
async function loadState() {
  try {
    const previous=state;
    state=await api('/api/state');
    if(!$('#operator').value && state.operator) $('#operator').value=state.operator;
    renderQueue(); renderRecords();
    if(state.template && state.template.path!==templateLoaded) renderTemplate();
    const oldImage=previous.images.find(row=>row.id===selectedImage), image=state.images.find(row=>row.id===selectedImage);
    if(image && JSON.stringify(oldImage)!==JSON.stringify(image)) renderImage();
    $('#connection-status').textContent=`本地服务已连接 · ${state.images.length} 张照片 · ${state.receipts.filter(row=>row.confirmed&&!row.voided).length} 条已确认记录`;
  } catch(error) {$('#connection-status').textContent='连接中断，请检查本地服务是否运行';}
}

function photoRow(image, selectable=false) {
  const labels={imported:'已导入',queued:'等待识别',running:'正在识别…',done:`${image.blocks.length} 处文字 · ${image.seconds.toFixed(1)} 秒`,error:'识别失败'};
  return `<div class="photo-row" draggable="true" data-drag-image="${image.id}">${selectable?`<input type="checkbox" aria-label="选择照片 ${escapeHtml(image.name)}" data-select-image="${image.id}" ${selectedPhotos.has(image.id)?'checked':''}>`:''}<button class="photo-preview" data-image="${image.id}" aria-label="查看照片 ${escapeHtml(image.name)}"><img src="${imageUrl(image.id)}" alt="" loading="lazy"></button><div class="photo-info"><button class="photo-name" data-image="${image.id}" title="${escapeHtml(image.name)}">${escapeHtml(image.name)}</button><span class="photo-status ${image.status}" title="${escapeHtml(image.error)}">${labels[image.status]}</span>${image.status==='error'?`<button class="text-button" data-retry="${image.id}">重试</button>`:''}</div><button class="text-button" data-move="${image.id}" aria-label="移动照片 ${escapeHtml(image.name)}">归组</button></div>`;
}
function renderQueue() {
  if(dragging || saving)return;
  const assigned=new Set(state.receipts.flatMap(row=>row.draft.image_ids));
  const ungrouped=state.images.filter(image=>!assigned.has(image.id));
  selectedPhotos=new Set([...selectedPhotos].filter(id=>!assigned.has(id)));
  $('#image-total').textContent=`${state.images.length} 张`;
  $('#ungrouped-count').textContent=ungrouped.length; $('#group-count').textContent=state.receipts.length;
  $('#ungrouped-list').innerHTML=ungrouped.map(image=>photoRow(image,true)).join('') || '<p class="hint">暂无待分组照片</p>';
  $('#group-list').innerHTML=state.receipts.slice().reverse().sort((a,b)=>Number(b.id===selectedReceipt)-Number(a.id===selectedReceipt)).map(receipt=>`<article class="group-card ${selectedReceipt===receipt.id?'selected':''}" data-drop-target="${receipt.id}"><button class="group-select" data-receipt="${receipt.id}"><strong>${escapeHtml(receipt.draft.fields.name?.value || `来料记录 ${state.receipts.indexOf(receipt)+1}`)}</strong><span class="group-meta"><span>${receipt.draft.image_ids.length} 张照片${receipt.draft.fields.lot?.value?` · 批号 ${escapeHtml(receipt.draft.fields.lot.value)}`:''}</span><span class="badge ${receipt.pending?'':'confirmed'}">${receipt.voided?'已作废':receipt.pending?(receipt.confirmed?'待重新确认':'待核对'):'已确认'}</span></span></button>${selectedReceipt===receipt.id?`<div class="group-images">${receipt.draft.image_ids.map(id=>state.images.find(image=>image.id===id)).filter(Boolean).map(image=>photoRow(image)).join('')}</div>`:''}</article>`).join('') || '<p class="hint">选中照片后新建一条来料记录。</p>';
}

async function selectReceipt(id, discard=false) {
  if(dirty && !discard && !window.confirm('当前字段有未保存的修改，是否放弃并切换记录？')) return;
  selectedReceipt=id;
  const receipt=currentReceipt(); if(!receipt) return;
  $('#review-form').hidden=true;$('#receipt-caption').textContent='正在加载记录…';
  loadedVersion=receipt.version; dirty=false; regionLabels=structuredClone(receipt.draft.region_labels || {});
  reviewedRegions=new Set(receipt.draft.reviewed_region_refs || []);
  const loadedCandidates=await api(`/api/receipts/${id}/candidates`);
  if(selectedReceipt!==id)return;
  candidates=loadedCandidates;
  fieldValues=Object.fromEntries(Object.keys(FIELDS).map(key=>[key,structuredClone(receipt.draft.fields[key] || (candidates[key]?.length===1?candidates[key][0]:blankField()))]));
  selectedImage=receipt.draft.image_ids.includes(selectedImage)?selectedImage:receipt.draft.image_ids[0] || null;
  productDecision=structuredClone(receipt.draft.product_decision || (receipt.confirmed?.product?{mode:'link',id:receipt.confirmed.product.id}:{mode:'new'}));
  $('#review-empty').hidden=true; $('#review-form').hidden=false; $('#reload-candidates').hidden=false;
  $('#receipt-caption').textContent=`${receipt.draft.image_ids.length} 张照片 · ${receipt.confirmed?`已确认 ${receipt.history.length} 次`:'待核对记录'}`;
  $('#grouping-reviewed').checked=receipt.draft.grouping_reviewed;
  $('#change-reason-row').hidden=!receipt.confirmed; $('#change-reason').value='';
  $('#draft-status').textContent=receipt.pending?'尚未确认的内容不会进入 Excel。':'已确认。修改后需要重新确认。';
  renderFields(); renderQueue(); renderImage(); renderProductChoices([]); renderHistory();
  $('#void-record').hidden=!!receipt.voided || !receipt.confirmed || receipt.draft.image_ids.length>0;
  $('#save-draft').hidden=!!receipt.voided; $('#confirm-record').hidden=!!receipt.voided;
  $('#reload-candidates').hidden=!!receipt.voided;
  if(receipt.voided) {
    $$('#review-form input,#review-form select,#review-form textarea,#review-form button').forEach(element=>{element.disabled=true;});
    $('#draft-status').textContent=`已作废：${receipt.voided.reason}。历史保留，不再导出。`;
  } else {$$('#grouping-reviewed,#match-products,#change-reason,#address-change,#save-draft,#confirm-record,#void-record').forEach(element=>{element.disabled=false;});}
}

function renderFields() {
  $('#fields-list').innerHTML=Object.entries(FIELDS).map(([key,label])=>{
    const value=fieldValues[key], choices=candidates[key] || [];
    return `<fieldset class="field ${activeField===key?'active-field':''}" data-field="${key}"><div class="field-heading"><label for="value-${key}">${label}</label><span class="evidence-count">${value.refs.length?`${value.refs.length} 处图片依据`:'待核实'}</span></div>${choices.length>1?`<select class="candidate-select" data-candidate="${key}" aria-label="${label}候选"><option value="">有 ${choices.length} 个候选，请对照图片选择</option>${choices.map((candidate,index)=>`<option value="${index}">${escapeHtml(candidate.value)}（${escapeHtml(candidate.reason)}）</option>`).join('')}</select>`:''}<div class="field-value"><input id="value-${key}" aria-label="${label}确认值" data-value="${key}" value="${escapeHtml(value.value)}" ${value.source==='missing'?'disabled':''} placeholder="${choices.length?'请核对识别结果':'选择文字或补填资料'}"><select aria-label="${label}来源" data-source="${key}"><option value="image" ${value.source==='image'?'selected':''}>图片文字</option><option value="external" ${value.source==='external'?'selected':''}>资料补填</option><option value="missing" ${value.source==='missing'?'selected':''}>未标注</option></select></div><details ${value.source!=='image'?'open':''}><summary>原文、来源与文字依据</summary><label class="detail-label" for="raw-${key}">提取原文</label><textarea id="raw-${key}" class="raw-text" rows="1" readonly aria-label="${label}提取原文">${escapeHtml(value.raw)}</textarea><label class="detail-label" for="note-${key}">说明或资料来源${value.source!=='image'?'（必填）':''}</label><textarea id="note-${key}" class="field-note" data-note="${key}" rows="2" aria-label="${label}说明或资料来源" placeholder="${value.source==='missing'?'说明已核对哪些包装位置，确认未标注':'例如：送货单编号、核实位置或补充说明'}">${escapeHtml(value.note)}</textarea><div class="references">${referenceHtml(key)}</div></details></fieldset>`;
  }).join('');
  $$('.field').forEach(element=>{
    const key=element.dataset.field;element.setAttribute('aria-label',`${FIELDS[key]}核对`);
    if((candidates[key] || []).some(candidate=>candidate.needs_review)) element.querySelector('.field-heading').insertAdjacentHTML('afterend','<p class="review-warning">存在跨行、日期或候选歧义，请重点核对原图。</p>');
  });
}
function referenceHtml(key) {
  return fieldValues[key].refs.map(id=>{const block=state.images.flatMap(image=>image.blocks).find(block=>block.id===id);if(!block)return '';return `<div class="reference"><div class="reference-top"><button type="button" class="text-button" data-highlight="${id}">${escapeHtml(block.text)}</button><button type="button" data-remove-ref="${id}" data-ref-field="${key}" aria-label="移除此文字依据">×</button></div><input data-region="${id}" value="${escapeHtml(regionLabels[id] || '')}" aria-label="文字区域校对 ${escapeHtml(block.text)}" placeholder="可选：整段区域的正确文字（含标签），用于样本"></div>`;}).join('') || '<p class="hint">点击原图中的文字框可关联当前字段。</p>';
}
function renderImage() {
  const image=state.images.find(row=>row.id===selectedImage);
  const receipt=currentReceipt();
  $('#image-tabs').innerHTML=(receipt?.draft.image_ids || []).map(id=>state.images.find(row=>row.id===id)).filter(Boolean).map(row=>`<button class="${row.id===selectedImage?'active':''}" data-image="${row.id}">${escapeHtml(row.name)}</button>`).join('');
  if(!image){$('#image-name').textContent='当前图片组没有照片';$('#ocr-status').textContent='';$('#ocr-blocks').innerHTML='';$('#image-stage').innerHTML='<div class="empty-state"><h3>请添加或归入照片</h3><p>调整归组后，需要重新检查当前记录的文字依据。</p></div>';return;}
  $('#image-name').textContent=image.name;
  $('#ocr-status').textContent=image.status==='done'?`${image.blocks.length} 处文字，${image.seconds.toFixed(1)} 秒`:({queued:'等待识别',running:'正在识别…',error:'识别失败，可重试',imported:'已导入'}[image.status]);
  const stage=$('#image-stage');
  const scale=Math.min((stage.clientWidth-36)/image.width,(Math.max(stage.clientHeight,250)-36)/image.height,1)*zoom;
  const width=Math.max(image.width*scale,1);
  stage.innerHTML=`<div class="image-surface" style="width:${width}px"><img src="${imageUrl(image.id)}" alt="${escapeHtml(image.name)}"><svg viewBox="0 0 ${image.width} ${image.height}" aria-label="文字识别区域">${image.blocks.map(block=>`<polygon data-block="${block.id}" class="${activeField && fieldValues[activeField]?.refs.includes(block.id)?'active':''}" points="${block.polygon.map(point=>point.join(',')).join(' ')}"><title>${escapeHtml(block.text)}</title></polygon>`).join('')}</svg></div>`;
  $('#ocr-blocks').innerHTML=image.blocks.map(block=>`<button type="button" class="ocr-token ${activeField && fieldValues[activeField]?.refs.includes(block.id)?'active':''}" data-block="${block.id}">${escapeHtml(block.text)}<small>${Math.round(block.score*100)} 分</small></button>`).join('') || `<p class="hint">${image.status==='done'?'未找到可读文字，请补拍清晰照片或依据核实资料补填。':image.status==='error'?escapeHtml(image.error):'识别完成后在这里查看文字。'}</p>`;
  $('#zoom-value').textContent=`${Math.round(zoom*100)}%`;
  $('#evidence-instruction').textContent=activeField?`正在核对「${FIELDS[activeField]}」：点选文字可添加或移除图片依据。`:'选择右侧字段后，点选文字区域可作为该字段的图片依据。';
}
function renderProductChoices(matches) {
  $('#product-candidates').innerHTML=`<label class="product-option"><input type="radio" name="product-choice" value="new" ${productDecision.mode==='new'?'checked':''}> 新建产品档案</label>`;
  if(productDecision.mode==='link' && !matches.some(item=>item.id===productDecision.id)) {
    const product=state.products.find(item=>item.id===productDecision.id);
    if(product)matches=[{...product,current:product.versions.at(-1),differences:[]} ,...matches];
  }
  matches.forEach(product=>{$('#product-candidates').insertAdjacentHTML('beforeend',`<div class="product-card"><label class="product-option"><input type="radio" name="product-choice" value="${product.id}" ${productDecision.id===product.id?'checked':''}><strong>${escapeHtml(product.code)}</strong><span class="muted">版本 ${product.current.version}</span></label><div class="comparison"><span>字段</span><span>本次内容</span><span>历史资料</span>${['name','specification','manufacturer','address'].map(key=>`<span>${FIELDS[key]}</span><span class="${product.differences.includes(key)?'different':''}">${escapeHtml(fieldValues[key].value || '待填写')}</span><span>${escapeHtml(product.current[key])}</span>`).join('')}</div></div>`);});
  $('#address-change-row').hidden=productDecision.mode!=='link'; $('#address-change').checked=!!productDecision.accept_address_change;
}
function renderHistory() {
  const receipt=currentReceipt(); $('#history-section').hidden=!receipt?.history.length;
  $('#history-content').innerHTML=(receipt?.history || []).slice().reverse().map(snapshot=>`<div class="history-entry"><strong>确认版本 ${snapshot.version} · ${escapeHtml(snapshot.operator)}</strong><p>${escapeHtml(snapshot.confirmed_at)}${snapshot.reason?`<br>${escapeHtml(snapshot.reason)}`:''}</p><table><tbody>${Object.entries(FIELDS).map(([key,label])=>`<tr><td>${label}</td><td>${escapeHtml(snapshot.fields[key].value)}</td></tr>`).join('')}</tbody></table></div>`).join('');
  $('#history-content').innerHTML+=(receipt?.changes || []).slice().reverse().map(change=>`<div class="history-entry"><strong>修改记录 · ${escapeHtml(change.operator)}</strong><p>${escapeHtml(change.at)}<br>${escapeHtml(change.reason || '草稿编辑')}</p><table><thead><tr><th>字段</th><th>修改前</th><th>修改后</th></tr></thead><tbody>${Object.entries(FIELDS).filter(([key])=>JSON.stringify(change.before.fields[key])!==JSON.stringify(change.after.fields[key])).map(([key,label])=>`<tr><td>${label}</td><td>${escapeHtml(change.before.fields[key]?.value || '空')}</td><td>${escapeHtml(change.after.fields[key]?.value || '空')}</td></tr>`).join('')}${JSON.stringify(change.before.image_ids)!==JSON.stringify(change.after.image_ids)?`<tr><td>照片归属</td><td>${change.before.image_ids.length} 张</td><td>${change.after.image_ids.length} 张</td></tr>`:''}</tbody></table></div>`).join('');
  if(receipt?.voided)$('#history-content').insertAdjacentHTML('afterbegin',`<div class="history-entry"><strong>作废记录 · ${escapeHtml(receipt.voided.operator)}</strong><p>${escapeHtml(receipt.voided.at)}<br>${escapeHtml(receipt.voided.reason)}</p></div>`);
}
function renderRecords() {
  const productFilter=$('#filter-product'), old=productFilter.value;
  productFilter.innerHTML='<option value="">全部产品</option>'+state.products.map(product=>`<option value="${product.id}">${escapeHtml(product.versions.at(-1).name)} · ${escapeHtml(product.versions.at(-1).specification)} · ${escapeHtml(product.code)}</option>`).join('');productFilter.value=old;
  const rows=state.receipts.filter(receipt=>receipt.confirmed&&!receipt.voided).filter(receipt=>{const record=receipt.confirmed;return (!filter.date_from||record.entered_at.slice(0,10)>=filter.date_from)&&(!filter.date_to||record.entered_at.slice(0,10)<=filter.date_to)&&(!filter.lot||record.fields.lot.value===filter.lot)&&(!filter.product_id||record.product?.id===filter.product_id);});
  $('#records-summary').textContent=`${rows.length} 条已确认记录。${rows.some(row=>row.pending)?'含待重新确认的修改；导出使用上一次已确认内容。':'未确认草稿不进入导出。'}`;
  $('#records-body').innerHTML=rows.map(receipt=>{const record=receipt.confirmed;return `<tr><td><strong>${escapeHtml(record.fields.name.value)}</strong><small>${escapeHtml(record.fields.specification.value)} · ${escapeHtml(record.product?.code)}</small></td><td>${escapeHtml(record.fields.manufacturer.value)}<small>${escapeHtml(record.fields.address.value)}</small></td><td>${escapeHtml(record.fields.lot.value)}</td><td>${escapeHtml(record.fields.production_date.value)}</td><td>${escapeHtml(record.fields.shelf_life.value)}</td><td>${escapeHtml(record.entered_at.replace('T',' ').replace('+08:00',''))}<small>${escapeHtml(record.operator)}</small></td><td><span class="badge ${receipt.pending?'':'confirmed'}">${receipt.pending?'修改待确认':'已确认'}</span></td><td><button data-edit-receipt="${receipt.id}">查看 / 修改</button></td></tr>`;}).join('') || '<tr><td colspan="8"><div class="empty-state"><h3>还没有符合条件的确认记录</h3><p>完成图片复核并确认后，记录会显示在这里。</p></div></td></tr>';
  $('#sample-count').textContent=state.samples.length;
  const activeSamples=state.samples.filter(sample=>sample.status==='active');
  $('#sample-count').textContent=`${activeSamples.length} 个有效候选`;
  $('#sample-list').innerHTML=state.samples.slice().reverse().map(sample=>`<div class="sample-item"><img src="/api/samples/${encodeURIComponent(sample.id)}/file" alt="${escapeHtml(sample.corrected_text)} 的文字区域" loading="lazy"><div><strong>${escapeHtml(sample.corrected_text)}</strong><p>识别原文：${escapeHtml(sample.ocr_text)}</p><p>${escapeHtml(sample.operator)} · ${escapeHtml(sample.confirmed_at)} · ${sample.status==='active'?'有效候选':'已由新版本替代'}</p></div></div>`).join('') || '<p class="hint">核对时填写图片文字区域的正确文本，确认后会在这里看到样本。</p>';
}
async function askDialog(title,html,confirmText='确定') {
  const dialog=$('#action-dialog');$('#dialog-title').textContent=title;$('#dialog-content').innerHTML=html;$('#dialog-confirm').textContent=confirmText;
  dialog.returnValue='';dialog.showModal();
  return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true}));
}
async function moveImage(id,targetId) {
  if(dirty&&!window.confirm('移动照片会重新载入字段，请先保存草稿。是否放弃未保存的修改并继续？'))return;
  const image=state.images.find(image=>image.id===id);if(!image)return;
  const source=state.receipts.find(receipt=>receipt.draft.image_ids.includes(id));
  const selectedTarget=targetId===undefined?(source?.id || ''):(targetId || '');
  const accepted=await askDialog('调整照片归属',`<p>${escapeHtml(image.name)}</p><p class="hint">请填写核实后的产品、批号或送货资料依据。调整后，受影响的记录需重新核对。</p><label>照片归属<select id="move-target" aria-label="照片归属"><option value="">待分组区</option>${state.receipts.filter(receipt=>!receipt.voided).map((receipt,index)=>`<option value="${receipt.id}" ${receipt.id===selectedTarget?'selected':''}>${escapeHtml(receipt.draft.fields.name?.value || `来料记录 ${index+1}`)} · ${escapeHtml(receipt.draft.fields.lot?.value || '批号待核对')} · ${receipt.draft.image_ids.length} 张</option>`).join('')}</select></label><label>归组操作人<input id="move-operator" value="${escapeHtml($('#operator').value)}" aria-label="归组操作人"></label><label>归组依据<textarea id="move-reason" rows="3" aria-label="归组依据" placeholder="如：依据送货单核实同一产品及批号，或补拍后确认照片归属"></textarea></label>`,'保存照片归属');
  if(!accepted)return;
  const target=$('#move-target').value || null;
  if((source?.id || null)===target){message('照片归属未改变。');return;}
  const expectedVersions=Object.fromEntries(state.receipts.filter(receipt=>receipt.id===source?.id||receipt.id===target).map(receipt=>[receipt.id,receipt.version]));
  await api(`/api/images/${id}/move`,{method:'POST',body:{target_id:target,operator:$('#move-operator').value.trim(),reason:$('#move-reason').value.trim(),expected_versions:expectedVersions}});
  dirty=false;await refresh();
  if(selectedReceipt)await selectReceipt(selectedReceipt,true);
  message('图片归属已调整。请重新核对受影响记录的字段和分组。');
}
function highlightBlock(id) {
  const image=state.images.find(image=>image.blocks.some(block=>block.id===id));if(!image)return;
  selectedImage=image.id;renderImage();
  $$('[data-block]').forEach(element=>element.classList.toggle('active',element.dataset.block===id));
}
function toggleEvidence(id) {
  if(!activeField || !currentReceipt()){message('请先选择右侧要核对的字段。',true);return;}
  const image=state.images.find(image=>image.blocks.some(block=>block.id===id));
  if(!currentReceipt().draft.image_ids.includes(image.id)){message('请先把这张照片归入当前图片组，再关联文字依据。',true);return;}
  const field=fieldValues[activeField], block=image.blocks.find(block=>block.id===id);
  invalidateLabels(activeField);
  field.source='image';
  if(field.refs.includes(id))field.refs=field.refs.filter(ref=>ref!==id);else field.refs.push(id);
  if(!field.value){field.value=block.text;field.raw=block.text;}
  setDirty();renderFields();$(`[data-field="${activeField}"] details`).open=true;renderImage();
}
function recordBody() {return {fields:fieldValues,operator:$('#operator').value.trim(),expected_version:loadedVersion,grouping_reviewed:$('#grouping-reviewed').checked,reason:$('#change-reason').value.trim(),product_decision:{...productDecision,accept_address_change:$('#address-change').checked},region_labels:regionLabels,reviewed_region_refs:[...reviewedRegions]};}
function readFilter(){return {date_from:$('#filter-from').value,date_to:$('#filter-to').value,lot:$('#filter-lot').value.trim(),product_id:$('#filter-product').value};}
function renderTemplate() {
  const template=state.template;if(!template)return;templateLoaded=template.path;
  $('#template-name').textContent=template.name;$('#template-form').hidden=false;
  $('#template-sheet').innerHTML=template.sheets.map(name=>`<option>${escapeHtml(name)}</option>`).join('');
  const config=template.config;
  if(config){$('#template-sheet').value=config.sheet;$('#template-start').value=config.start_row;$('#template-end').value=config.end_row;$('#date-mode').value=config.date_mode;$('#missing-mode').value=config.missing_mode;}
  $('#column-mapping').innerHTML=Object.entries({...FIELDS,entered_at:'录入时间',operator:'操作人'}).map(([key,label])=>`<label>${label}列<input aria-label="${label}列" data-column="${key}" value="${escapeHtml(config?.columns[key] || '')}" placeholder="如 A" pattern="[A-Za-z]{1,3}" required></label>`).join('');
  $('#template-status').textContent=config?'已保存当前模板映射':'请按现有表头填写列字母';
}

document.addEventListener('click',event=>{
  const button=event.target.closest('button'); if(!button)return;
  if(button.dataset.page)showPage(button.dataset.page);
  if(button.dataset.image){selectedImage=button.dataset.image;zoom=1;renderImage();}
  if(button.dataset.receipt)action(button,()=>selectReceipt(button.dataset.receipt));
  if(button.dataset.editReceipt)action(button,async()=>{showPage('workbench');await selectReceipt(button.dataset.editReceipt);});
  if(button.dataset.block)toggleEvidence(button.dataset.block);
  if(button.dataset.highlight)highlightBlock(button.dataset.highlight);
  if(button.dataset.removeRef){const key=button.dataset.refField;invalidateLabels(key);fieldValues[key].refs=fieldValues[key].refs.filter(id=>id!==button.dataset.removeRef);setDirty();renderFields();$(`[data-field="${key}"] details`).open=true;renderImage();}
  if(button.dataset.move)action(button,()=>moveImage(button.dataset.move));
  if(button.dataset.retry)action(button,async()=>{await api(`/api/images/${button.dataset.retry}/retry`,{method:'POST',body:{}});await refresh();message('已重新加入识别队列。');});
});
$('#image-stage').addEventListener('click',event=>{const polygon=event.target.closest('polygon[data-block]');if(polygon)toggleEvidence(polygon.dataset.block);});
$('#image-import').addEventListener('change',event=>action(null,async()=>{
  const files=[...event.target.files]; if(!files.length)return;const body=new FormData();files.forEach(file=>body.append('files',file));
  $('#import-progress').hidden=false;$('#import-progress').textContent=`正在导入 ${files.length} 张照片…`;
  try{const result=await api('/api/images',{method:'POST',body});await refresh();message(`已导入 ${result.images.length} 张照片，识别任务已排队。`);if(result.errors.length)message(result.errors.map(error=>`${error.name}：${error.error}`).join('\n'),true);}finally{$('#import-progress').hidden=true;event.target.value='';}
}));
document.addEventListener('change',event=>{
  const target=event.target;
  if(target.dataset.selectImage){target.checked?selectedPhotos.add(target.dataset.selectImage):selectedPhotos.delete(target.dataset.selectImage);}
  if(target.dataset.source){const key=target.dataset.source;invalidateLabels(key);fieldValues[key].source=target.value;if(target.value==='missing')fieldValues[key].value='未标注';else if(fieldValues[key].value==='未标注')fieldValues[key].value='';setDirty();renderFields();}
  if(target.name==='product-choice'){productDecision=target.value==='new'?{mode:'new'}:{mode:'link',id:target.value};$('#address-change-row').hidden=productDecision.mode!=='link';setDirty();}
  if(target.dataset.candidate && target.value!==''){const key=target.dataset.candidate;invalidateLabels(key);fieldValues[key]=structuredClone(candidates[key][Number(target.value)]);invalidateLabels(key);activeField=key;setDirty();renderFields();const first=fieldValues[key].refs[0];if(first)highlightBlock(first);}
});
$('#fields-list').addEventListener('input',event=>{const target=event.target;if(target.dataset.value){const field=fieldValues[target.dataset.value];field.value=target.value;if(field.source==='external'&&!field.refs.length)field.raw=target.value;setDirty();invalidateLabels(target.dataset.value);}if(target.dataset.note){fieldValues[target.dataset.note].note=target.value;setDirty();}if(target.dataset.region){regionLabels[target.dataset.region]=target.value;reviewedRegions.add(target.dataset.region);setDirty();}});
$('#fields-list').addEventListener('focusin',event=>{const field=event.target.closest('[data-field]');if(field){activeField=field.dataset.field;$$('.field').forEach(row=>row.classList.toggle('active-field',row.dataset.field===activeField));renderImage();}});
$('#review-form').addEventListener('change',event=>{if(event.target.matches('#grouping-reviewed,#change-reason,#address-change'))setDirty();});
document.addEventListener('dragstart',event=>{const photo=event.target.closest('[data-drag-image]');if(photo){dragging=true;event.dataTransfer.setData('text/plain',photo.dataset.dragImage);event.dataTransfer.effectAllowed='move';}});
document.addEventListener('dragend',()=>{dragging=false;$$('.drag-over').forEach(zone=>zone.classList.remove('drag-over'));});
document.addEventListener('dragover',event=>{const zone=event.target.closest('[data-drop-target],#ungrouped-zone');if(zone){event.preventDefault();zone.classList.add('drag-over');event.dataTransfer.dropEffect='move';}});
document.addEventListener('dragleave',event=>{const zone=event.target.closest('[data-drop-target],#ungrouped-zone');if(zone&&(!(event.relatedTarget instanceof Node)||!zone.contains(event.relatedTarget)))zone.classList.remove('drag-over');});
document.addEventListener('drop',event=>{const zone=event.target.closest('[data-drop-target],#ungrouped-zone');if(!zone)return;event.preventDefault();dragging=false;zone.classList.remove('drag-over');const id=event.dataTransfer.getData('text/plain');if(state.images.some(image=>image.id===id))action(null,()=>moveImage(id,zone.dataset.dropTarget || null));});
$('#create-group').addEventListener('click',event=>action(event.currentTarget,async()=>{if(!selectedPhotos.size)throw Error('请先在待分组区选择照片。');if(dirty&&!window.confirm('当前字段有未保存的修改，是否放弃并建立新记录？'))return;const receipt=await api('/api/receipts',{method:'POST',body:{image_ids:[...selectedPhotos]}});selectedPhotos.clear();await refresh();await selectReceipt(receipt.id,true);}));
$('#review-form').addEventListener('submit',event=>{event.preventDefault();action($('#confirm-record'),()=>saveRecord(true));});
$('#save-draft').addEventListener('click',event=>action(event.currentTarget,()=>saveRecord(false)));
$('#void-record').addEventListener('click',event=>action(event.currentTarget,async()=>{
  const accepted=await askDialog('作废空记录','<p>仅适用于照片已全部移出的重复或错误记录。作废后不再导出，确认历史和作废原因继续保留。</p><label>作废原因<textarea id="void-reason" aria-label="作废原因" rows="3"></textarea></label>','确认作废');
  if(!accepted)return;
  await api(`/api/receipts/${selectedReceipt}/void`,{method:'POST',body:{operator:$('#operator').value.trim(),reason:$('#void-reason').value.trim(),expected_version:loadedVersion}});
  dirty=false;await refresh();await selectReceipt(selectedReceipt,true);message('空记录已作废，历史保留，不再进入 Excel。');
}));
$('#suggest-groups').addEventListener('click',event=>action(event.currentTarget,async()=>{
  const assigned=new Set(state.receipts.flatMap(receipt=>receipt.draft.image_ids));
  const images=state.images.filter(image=>!assigned.has(image.id)&&(!selectedPhotos.size||selectedPhotos.has(image.id)));
  if(!images.length)throw Error('请先导入待分组照片。');
  if(images.some(image=>image.status!=='done'))throw Error('请等待所选照片完成识别，失败的照片可重试或手动归组。');
  const result=await api('/api/groups/suggest',{method:'POST',body:{image_ids:images.map(image=>image.id)}});
  const accepted=await askDialog('检查建议分组',`<p class="hint">这里只根据文字线索建议。每组仍需检查实际照片；每次来料应单独登记。</p>${result.groups.map((group,index)=>`<div class="proposal"><label><input type="checkbox" class="proposal-check" value="${index}" checked> 图片组 ${index+1}（${group.image_ids.length} 张）</label><p>${group.image_ids.map(id=>escapeHtml(state.images.find(image=>image.id===id).name)).join('<br>')}</p><p>${escapeHtml(group.reason)}</p></div>`).join('')}${result.ungrouped.length?`<h3 style="margin-top:15px">继续留在待分组区</h3>${result.ungrouped.map(item=>`<div class="proposal"><strong>${escapeHtml(state.images.find(image=>image.id===item.image_id).name)}</strong><p>${escapeHtml(item.reason)}</p></div>`).join('')}`:''}${!result.groups.length?'<p class="hint">没有足够线索建立分组。请补拍或核实资料后手动归组。</p>':''}`,'应用建议并建立记录');
  if(!accepted)return;
  const chosen=$$('.proposal-check:checked').map(input=>result.groups[Number(input.value)]);
  if(!chosen.length){message('照片保留在待分组区。');return;}
  if(dirty&&!window.confirm('当前字段有未保存的修改，是否放弃并查看新分组？'))return;
  let first;
  for(const group of chosen){const receipt=await api('/api/receipts',{method:'POST',body:{image_ids:group.image_ids}});first ||= receipt.id;}
  selectedPhotos.clear();await refresh();await selectReceipt(first,true);message(`已建立 ${chosen.length} 个建议图片组，请逐组检查照片归属。`);
}));
$('#reload-candidates').addEventListener('click',event=>action(event.currentTarget,async()=>{candidates=await api(`/api/receipts/${selectedReceipt}/candidates`);for(const key of Object.keys(FIELDS)){if(!fieldValues[key].value&&candidates[key].length===1)fieldValues[key]=structuredClone(candidates[key][0]);}renderFields();message('已更新候选；已经填写的内容保留，请对照图片核实。');}));
$('#match-products').addEventListener('click',event=>action(event.currentTarget,async()=>{const body=Object.fromEntries(['name','specification','manufacturer','address'].map(key=>[key,fieldValues[key].value]));const matches=await api('/api/products/suggest',{method:'POST',body});renderProductChoices(matches);if(!matches.length)message('未找到相近历史产品，请核对后新建档案。');}));
$('#zoom-in').addEventListener('click',()=>{zoom=Math.min(zoom+.25,4);renderImage();});$('#zoom-out').addEventListener('click',()=>{zoom=Math.max(zoom-.25,.25);renderImage();});
$('#template-upload').addEventListener('change',event=>action(null,async()=>{if(!event.target.files.length)return;$('#template-form').hidden=true;const body=new FormData();body.append('file',event.target.files[0]);await api('/api/template',{method:'POST',body});await refresh();renderTemplate();message('模板已上传，请核对工作表、数据区域和字段列。');event.target.value='';}));
$('#template-form').addEventListener('submit',event=>{event.preventDefault();action(event.submitter,async()=>{const body={sheet:$('#template-sheet').value,start_row:Number($('#template-start').value),end_row:Number($('#template-end').value),date_mode:$('#date-mode').value,missing_mode:$('#missing-mode').value,columns:Object.fromEntries($$('[data-column]').map(input=>[input.dataset.column,input.value.trim().toUpperCase()]))};if(new Set(Object.values(body.columns)).size!==9)throw Error('九个字段必须分别映射到不同的列。');if(body.start_row>body.end_row)throw Error('数据起始行不能大于结束行。');await api('/api/template/config',{method:'PUT',body});$('#template-status').textContent='映射已保存';message('模板映射已保存。');});});
$('#apply-filter').addEventListener('click',()=>{filter=readFilter();if(filter.date_from&&filter.date_to&&filter.date_from>filter.date_to){message('起始日期不能晚于结束日期。',true);return;}renderRecords();});
$('#clear-filter').addEventListener('click',()=>{$('#filter-from').value='';$('#filter-to').value='';$('#filter-product').value='';$('#filter-lot').value='';filter={};renderRecords();});
$('#export-records').addEventListener('click',event=>action(event.currentTarget,async()=>{filter=readFilter();renderRecords();const result=await api('/api/exports',{method:'POST',body:filter});$('#export-result').innerHTML=`<a href="${escapeHtml(result.url)}" download="${escapeHtml(result.name)}">下载 Excel（${result.count} 条记录）</a>${result.pending_count?`<p class="hint">${result.pending_count} 条记录存在待确认修改，本次采用其上一次确认内容。</p>`:''}`;message(`Excel 已生成，共 ${result.count} 条记录。`);}));
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
refresh();setInterval(refresh,2500);
