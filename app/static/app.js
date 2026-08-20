(() => {
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = value => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const escapeSelectorValue = value => window.CSS?.escape ? CSS.escape(value) : String(value).replace(/["\\]/g, '\\$&');

  // ---------------- Upload Progress Overlay ----------------
  function showUploadProgress(label) {
    let overlay = qs('#uploadProgressOverlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'uploadProgressOverlay';
      overlay.className = 'upload-overlay';
      overlay.innerHTML = '<div class="upload-progress-card"><div class="upload-progress-icon">\u21e7</div><div class="upload-progress-info"><div class="upload-progress-label"></div><div class="upload-progress-bar-wrap"><div class="upload-progress-bar"></div></div><div class="upload-progress-pct">0%</div></div></div>';
      document.body.appendChild(overlay);
    }
    qs('.upload-progress-label', overlay).textContent = label || '업로드 중...';
    qs('.upload-progress-bar', overlay).style.width = '0%';
    qs('.upload-progress-pct', overlay).textContent = '0%';
    overlay.classList.add('show');
    return overlay;
  }
  function updateUploadProgress(overlay, pct) {
    qs('.upload-progress-bar', overlay).style.width = pct + '%';
    qs('.upload-progress-pct', overlay).textContent = Math.round(pct) + '%';
  }
  function hideUploadProgress(overlay) { overlay?.classList.remove('show'); }
  function uploadFormWithProgress(form, label) {
    if (form.dataset.uploading === '1') return;
    form.dataset.uploading = '1';
    qsa('button[type="submit"]', form).forEach(button => { button.disabled = true; button.dataset.originalText = button.textContent; button.textContent = '처리 중...'; });
    const overlay = showUploadProgress(label);
    const xhr = new XMLHttpRequest();
    const reset = () => { form.dataset.uploading = '0'; qsa('button[type="submit"]', form).forEach(button => { button.disabled = false; if (button.dataset.originalText) button.textContent = button.dataset.originalText; }); };
    xhr.open(form.method || 'POST', form.action);
    xhr.upload.addEventListener('progress', e => { if (e.lengthComputable) updateUploadProgress(overlay, (e.loaded / e.total) * 100); });
    xhr.addEventListener('load', () => {
      hideUploadProgress(overlay);
      if (xhr.status >= 200 && xhr.status < 400) { window.location.href = xhr.responseURL || window.location.href; }
      else { reset(); alert('업로드에 실패했습니다. (' + xhr.status + ')'); }
    });
    xhr.addEventListener('error', () => { reset(); hideUploadProgress(overlay); alert('업로드 중 오류가 발생했습니다.'); });
    xhr.send(new FormData(form));
  }

  qsa('[data-open-dialog]').forEach(btn => btn.addEventListener('click', () => document.getElementById(btn.dataset.openDialog)?.showModal()));
  qsa('[data-close-dialog]').forEach(btn => btn.addEventListener('click', () => btn.closest('dialog')?.close()));

  qsa('[data-inline-upload]').forEach(input => input.addEventListener('change', () => {
    const form = input.closest('form');
    if (form && input.files?.length) uploadFormWithProgress(form, '업로드 중...');
  }));

  qsa('form.settings-form, form.source-link-form').forEach(form => form.addEventListener('submit', () => {
    qsa('button[type="submit"]', form).forEach(button => { button.disabled = true; button.dataset.originalText = button.textContent; button.textContent = '저장 중...'; });
  }));

  qsa('[data-menu]').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    qsa('.context-menu.open').forEach(m => { if (m.id !== btn.dataset.menu) m.classList.remove('open'); });
    document.getElementById(btn.dataset.menu)?.classList.toggle('open');
  }));
  document.addEventListener('click', () => qsa('.context-menu.open').forEach(m => m.classList.remove('open')));

  const renameDialog = qs('#renameDialog');
  qsa('.rename-trigger').forEach(btn => btn.addEventListener('click', () => {
    qs('#renamePath').value = btn.dataset.path;
    qs('#renameName').value = btn.dataset.name;
    renameDialog?.showModal();
  }));

  const fileInput = qs('#fileUploadInput');
  const fileProxy = qs('#fileUploadProxy');
  const fileForm = qs('#fileUploadForm');
  const fileUploadPath = qs('#fileUploadPath');
  if (fileInput && fileProxy && fileForm) fileInput.addEventListener('change', () => {
    const dt = new DataTransfer(); [...fileInput.files].forEach(f => dt.items.add(f));
    fileProxy.files = dt.files;
    uploadFormWithProgress(fileForm, '파일 업로드 중...');
  });

  qsa('.hash-btn').forEach(btn => btn.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(btn.dataset.hash); const old = btn.textContent; btn.textContent = '복사됨'; setTimeout(() => btn.textContent = old, 1200); }
    catch { alert(btn.dataset.hash); }
  }));
  qsa('.copy-share').forEach(wrap => wrap.querySelector('button')?.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(wrap.dataset.url); wrap.querySelector('button').textContent = '복사됨'; }
    catch { prompt('공유 링크', wrap.dataset.url); }
  }));

  // ---------------- Project Resources ----------------
  const resourceInput = qs('#resourceFileInput');
  const resourceDropZone = qs('#resourceDropZone');
  const resourceTitles = qs('#resourceFileTitles');
  const resourceForm = qs('#resourceUploadForm');
  function renderResourceTitles(files) {
    if (!resourceTitles) return;
    resourceTitles.innerHTML = [...(files || [])].map(file => {
      const title = file.name.replace(/\.[^.]+$/, '');
      return `<label>${escapeHtml(file.name)}<input name="titles" value="${escapeHtml(title)}" maxlength="300"></label>`;
    }).join('');
  }
  resourceInput?.addEventListener('change', () => renderResourceTitles(resourceInput.files));
  if (resourceDropZone && resourceInput) {
    ['dragenter', 'dragover'].forEach(type => resourceDropZone.addEventListener(type, e => { e.preventDefault(); resourceDropZone.classList.add('dragover'); }));
    ['dragleave', 'drop'].forEach(type => resourceDropZone.addEventListener(type, e => { e.preventDefault(); resourceDropZone.classList.remove('dragover'); }));
    resourceDropZone.addEventListener('drop', e => {
      const files = e.dataTransfer?.files;
      if (!files?.length) return;
      const transfer = new DataTransfer(); [...files].forEach(file => transfer.items.add(file));
      resourceInput.files = transfer.files;
      renderResourceTitles(resourceInput.files);
    });
  }
  resourceForm?.addEventListener('submit', e => { e.preventDefault(); uploadFormWithProgress(resourceForm, '자료 업로드 중...'); });

  // ---------------- Smart Upload ----------------
  const zone = qs('#smartDropZone');
  const chooser = qs('#chooseSmartFiles');
  const smartInput = qs('#smartFileInput');
  const preview = qs('#smartPreview');
  const previewBody = qs('#smartPreviewBody');
  const proxy = qs('#uploadFilesProxy');
  const versionWrap = qs('#versionOverrideWrap');
  const submit = qs('#submitSmartUpload');
  const cancel = qs('#cancelPreview');

  async function analyze(files) {
    if (!files?.length) return;
    const names = [...files].map(f => f.name);
    const res = await fetch('/api/smart-upload/analyze', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({filenames:names})});
    if (!res.ok) { alert('파일 분석에 실패했습니다.'); return; }
    const data = await res.json();
    const dt = new DataTransfer(); [...files].forEach(f => dt.items.add(f)); proxy.files = dt.files;
    previewBody.innerHTML = `<div class="analysis-table"><div class="analysis-row header"><div>파일</div><div>버전</div><div>유형</div></div>${data.files.map(f => `<div class="analysis-row"><div><strong>${escapeHtml(f.filename)}</strong></div><div class="${f.needs_version?'needs':''}">${f.version ? 'v'+escapeHtml(f.version) : '입력 필요'}</div><div>${escapeHtml(f.file_type)}</div></div>`).join('')}</div>${Object.keys(data.groups).length > 1 ? `<div class="alert">서로 다른 버전이 감지되어 각 버전별 릴리스로 자동 분리됩니다: ${Object.keys(data.groups).map(v=>'v'+escapeHtml(v)).join(', ')}</div>`:''}`;
    versionWrap.classList.toggle('hidden', data.unresolved.length === 0);
    submit.textContent = `${files.length}개 파일 업로드`;
    preview.classList.remove('hidden');
    preview.scrollIntoView({behavior:'smooth', block:'start'});
  }
  if (chooser && smartInput) { chooser.addEventListener('click',()=>smartInput.click()); smartInput.addEventListener('change',()=>analyze(smartInput.files)); }
  if (zone) {
    ['dragenter','dragover'].forEach(t=>zone.addEventListener(t,e=>{e.preventDefault();zone.classList.add('dragover')}));
    ['dragleave','drop'].forEach(t=>zone.addEventListener(t,e=>{e.preventDefault();zone.classList.remove('dragover')}));
    zone.addEventListener('drop',e=>analyze(e.dataTransfer.files));
  }
  cancel?.addEventListener('click',()=>{preview.classList.add('hidden'); smartInput.value=''; proxy.value='';});
  const smartForm = qs('#smartUploadForm');
  if (smartForm) smartForm.addEventListener('submit', e => { e.preventDefault(); uploadFormWithProgress(smartForm, '릴리스 업로드 중...'); });

  // ---------------- Explorer folder tree ----------------
  const explorer = qs('#fileExplorerLayout');
  if (!explorer) return;

  const currentPath = explorer.dataset.currentPath || '';
  const treePanel = qs('#folderTreePanel');
  const rootNode = qs('.root-node', treePanel);
  const treeLoading = qs('#treeLoading');
  const treeError = qs('#treeError');
  const treeRefresh = qs('#treeRefresh');
  const treeSearch = qs('#folderTreeSearch');
  const treeCollapse = qs('#treeCollapse');
  const treeReopen = qs('#treeReopen');
  const treeResizer = qs('#treeResizer');
  const mobileToggle = qs('#folderTreeMobileToggle');
  const treeContextMenu = qs('#treeContextMenu');
  const treeUploadInput = qs('#treeUploadInput');
  const folderDialog = qs('#folderDialog');
  const folderDialogPath = qs('#folderDialogPath');
  const folderDialogLocation = qs('#folderDialogLocation');
  let contextFolderPath = '';
  let contextFolderManaged = false;
  let uploadTargetPath = '';

  const pathUrl = path => path ? `/files?path=${encodeURIComponent(path)}` : '/files';
  const parentPath = path => {
    const bits = String(path || '').split('/').filter(Boolean);
    bits.pop();
    return bits.join('/');
  };

  function showTreeError(message) {
    treeLoading?.classList.add('hidden');
    if (treeError) {
      treeError.textContent = message;
      treeError.classList.remove('hidden');
    }
  }

  function createTreeNode(folder) {
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.dataset.treePath = folder.path;
    node.dataset.managed = folder.managed ? '1' : '0';
    node.innerHTML = `
      <div class="tree-node-row${folder.path === currentPath ? ' active' : ''}" data-tree-row data-path="${escapeHtml(folder.path)}" data-managed="${folder.managed ? '1' : '0'}">
        <button type="button" class="tree-expander" data-tree-expand aria-label="하위 폴더 펼치기">▸</button>
        <span class="tree-folder-icon">▰</span>
        <a class="tree-label" href="${pathUrl(folder.path)}" title="${escapeHtml(folder.path)}">${escapeHtml(folder.name)}</a>${folder.managed ? '<span class="managed-tree-badge">PROJECT</span>' : ''}
        <button type="button" class="tree-node-menu-btn" data-tree-menu-button title="폴더 작업">•••</button>
      </div>
      <div class="tree-children hidden" data-tree-children></div>`;
    bindTreeNode(node);
    return node;
  }

  async function loadChildren(node, {force = false} = {}) {
    if (!node) return [];
    const path = node.dataset.treePath || '';
    const children = qs('[data-tree-children]', node);
    const expander = qs('[data-tree-expand]', node);
    if (!children) return [];
    if (node.dataset.loaded === '1' && !force) return qsa(':scope > .tree-node', children);

    expander?.classList.add('loading');
    try {
      const res = await fetch(`/api/files/tree?path=${encodeURIComponent(path)}`, {headers:{'Accept':'application/json'}});
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || '폴더를 불러오지 못했습니다.');
      children.innerHTML = '';
      (data.folders || []).forEach(folder => children.appendChild(createTreeNode(folder)));
      node.dataset.loaded = '1';
      if (!(data.folders || []).length) {
        expander?.classList.add('leaf');
        expander?.setAttribute('aria-label', '하위 폴더 없음');
      } else {
        expander?.classList.remove('leaf');
      }
      return qsa(':scope > .tree-node', children);
    } finally {
      expander?.classList.remove('loading');
    }
  }

  async function expandNode(node, {force = false} = {}) {
    if (!node) return;
    const children = qs('[data-tree-children]', node);
    const expander = qs('[data-tree-expand]', node);
    try {
      await loadChildren(node, {force});
      children?.classList.remove('hidden');
      expander?.classList.add('expanded');
      if (!expander?.classList.contains('leaf')) expander.textContent = '▾';
      node.dataset.expanded = '1';
    } catch (err) {
      showTreeError(err.message || '폴더를 불러오지 못했습니다.');
    }
  }

  function collapseNode(node) {
    const children = qs('[data-tree-children]', node);
    const expander = qs('[data-tree-expand]', node);
    children?.classList.add('hidden');
    expander?.classList.remove('expanded');
    if (!expander?.classList.contains('leaf')) expander.textContent = '▸';
    node.dataset.expanded = '0';
  }

  function bindTreeNode(node) {
    const expander = qs('[data-tree-expand]', node);
    const row = qs('[data-tree-row]', node);
    const menuButton = qs('[data-tree-menu-button]', node);

    expander?.addEventListener('click', async e => {
      e.preventDefault(); e.stopPropagation();
      if (expander.classList.contains('leaf')) return;
      if (node.dataset.expanded === '1') collapseNode(node); else await expandNode(node);
    });

    menuButton?.addEventListener('click', e => {
      e.preventDefault(); e.stopPropagation();
      contextFolderPath = row?.dataset.path || '';
      contextFolderManaged = row?.dataset.managed === '1';
      openTreeContextMenu(e.clientX, e.clientY);
    });

    row?.addEventListener('contextmenu', e => {
      e.preventDefault();
      contextFolderPath = row.dataset.path || '';
      contextFolderManaged = row.dataset.managed === '1';
      openTreeContextMenu(e.clientX, e.clientY);
    });

    row?.addEventListener('dragenter', e => {
      e.preventDefault();
      row.classList.add('drop-target');
    });
    row?.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = e.dataTransfer.types.includes('application/x-nuni-path') ? 'move' : 'copy';
      row.classList.add('drop-target');
    });
    row?.addEventListener('dragleave', e => {
      if (!row.contains(e.relatedTarget)) row.classList.remove('drop-target');
    });
    row?.addEventListener('drop', async e => {
      e.preventDefault(); e.stopPropagation();
      row.classList.remove('drop-target');
      const destination = row.dataset.path || '';
      const source = e.dataTransfer.getData('application/x-nuni-path');
      if (row.dataset.managed === '1' || source && source.startsWith('프로젝트/')) {
        alert('프로젝트에서 관리되는 항목입니다. 프로젝트 관리 화면에서 변경하세요.');
        return;
      }
      if (source) {
        if (destination === parentPath(source)) return;
        await moveEntry(source, destination);
        return;
      }
      if (e.dataTransfer.files?.length) await uploadFilesTo(destination, e.dataTransfer.files);
    });
  }

  async function moveEntry(source, destinationDir) {
    const name = source.split('/').pop();
    if (!confirm(`'${name}' 항목을 선택한 폴더로 이동할까요?`)) return;
    try {
      const res = await fetch('/api/files/move', {
        method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'},
        body:JSON.stringify({source, destination_dir:destinationDir})
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || '이동에 실패했습니다.');
      window.location.reload();
    } catch (err) { alert(err.message || '이동에 실패했습니다.'); }
  }

  async function uploadFilesTo(path, files) {
    if (!files?.length || !fileForm || !fileProxy || !fileUploadPath) return;
    uploadTargetPath = path;
    const dt = new DataTransfer(); [...files].forEach(file => dt.items.add(file));
    fileProxy.files = dt.files;
    fileUploadPath.value = path;
    uploadFormWithProgress(fileForm, '파일 업로드 중...');
  }

  function openTreeContextMenu(x, y) {
    if (!treeContextMenu) return;
    qsa('[data-tree-action="new-folder"],[data-tree-action="upload"]', treeContextMenu).forEach(button => {
      button.disabled = contextFolderManaged;
      button.classList.toggle('disabled-action', contextFolderManaged);
      button.title = contextFolderManaged ? '프로젝트에서 관리되는 항목입니다.' : '';
    });
    treeContextMenu.classList.add('open');
    const width = 178, height = 164;
    treeContextMenu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - width - 8))}px`;
    treeContextMenu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - height - 8))}px`;
  }

  function closeTreeContextMenu() { treeContextMenu?.classList.remove('open'); }
  document.addEventListener('click', e => { if (!treeContextMenu?.contains(e.target)) closeTreeContextMenu(); });
  window.addEventListener('blur', closeTreeContextMenu);
  window.addEventListener('resize', closeTreeContextMenu);

  treeContextMenu?.addEventListener('click', async e => {
    const button = e.target.closest('[data-tree-action]');
    if (!button) return;
    const action = button.dataset.treeAction;
    if (contextFolderManaged && ['new-folder', 'upload'].includes(action)) {
      closeTreeContextMenu();
      alert('프로젝트에서 관리되는 항목입니다. 프로젝트 관리 화면에서 변경하세요.');
      return;
    }
    closeTreeContextMenu();
    if (action === 'open') { window.location.href = pathUrl(contextFolderPath); return; }
    if (action === 'new-folder') {
      if (folderDialogPath) folderDialogPath.value = contextFolderPath;
      if (folderDialogLocation) folderDialogLocation.textContent = contextFolderPath ? `${contextFolderPath}에 생성` : 'Repository에 생성';
      folderDialog?.showModal();
      return;
    }
    if (action === 'upload') {
      uploadTargetPath = contextFolderPath;
      treeUploadInput?.click();
      return;
    }
    if (action === 'refresh') {
      const node = qs(`.tree-node[data-tree-path="${escapeSelectorValue(contextFolderPath)}"]`, treePanel);
      if (node) await expandNode(node, {force:true});
    }
  });

  treeUploadInput?.addEventListener('change', () => {
    if (treeUploadInput.files?.length) uploadFilesTo(uploadTargetPath, treeUploadInput.files);
  });

  qs('.head-actions [data-open-dialog="folderDialog"]')?.addEventListener('click', () => {
    if (folderDialogPath) folderDialogPath.value = currentPath;
    if (folderDialogLocation) folderDialogLocation.textContent = currentPath ? `${currentPath}에 생성` : 'Repository에 생성';
  });

  qsa('.file-entry-row').forEach(row => {
    row.addEventListener('dragstart', e => {
      if (row.dataset.managed === '1') { e.preventDefault(); return; }
      const path = row.dataset.entryPath || '';
      e.dataTransfer.setData('application/x-nuni-path', path);
      e.dataTransfer.setData('text/plain', path);
      e.dataTransfer.effectAllowed = 'move';
      row.classList.add('dragging');
    });
    row.addEventListener('dragend', () => row.classList.remove('dragging'));
  });

  async function revealCurrentPath() {
    treeLoading?.classList.remove('hidden');
    treeError?.classList.add('hidden');
    try {
      await expandNode(rootNode);
      let parent = rootNode;
      const parts = currentPath.split('/').filter(Boolean);
      let accum = '';
      for (const part of parts) {
        accum = accum ? `${accum}/${part}` : part;
        const children = qs('[data-tree-children]', parent);
        let next = children ? qs(`:scope > .tree-node[data-tree-path="${escapeSelectorValue(accum)}"]`, children) : null;
        if (!next) break;
        qs('[data-tree-row]', next)?.classList.add('active');
        if (accum !== currentPath) await expandNode(next);
        parent = next;
      }
      const active = qs('.tree-node-row.active', treePanel);
      active?.scrollIntoView({block:'nearest'});
    } catch (err) {
      showTreeError(err.message || '폴더 트리를 불러오지 못했습니다.');
    } finally {
      treeLoading?.classList.add('hidden');
    }
  }

  treeRefresh?.addEventListener('click', async () => {
    treeError?.classList.add('hidden');
    rootNode.dataset.loaded = '0';
    qs('[data-tree-children]', rootNode).innerHTML = '';
    await revealCurrentPath();
  });

  function applyTreeFilter() {
    const query = (treeSearch?.value || '').trim().toLocaleLowerCase('ko-KR');
    function visit(node) {
      const row = qs(':scope > [data-tree-row]', node);
      const label = qs('.tree-label', row)?.textContent?.toLocaleLowerCase('ko-KR') || '';
      const childNodes = qsa(':scope > [data-tree-children] > .tree-node', node);
      const childMatch = childNodes.map(visit).some(Boolean);
      const selfMatch = !query || label.includes(query);
      const visible = selfMatch || childMatch || node === rootNode;
      node.classList.toggle('tree-filter-hidden', !visible);
      if (query && childMatch) {
        qs(':scope > [data-tree-children]', node)?.classList.remove('hidden');
        qs(':scope > [data-tree-row] [data-tree-expand]', node)?.classList.add('expanded');
      }
      return visible;
    }
    visit(rootNode);
  }
  treeSearch?.addEventListener('input', applyTreeFilter);

  function setTreeCollapsed(collapsed) {
    explorer.classList.toggle('tree-collapsed', collapsed);
    localStorage.setItem('nuni.folderTree.collapsed', collapsed ? '1' : '0');
  }
  treeCollapse?.addEventListener('click', () => setTreeCollapsed(true));
  treeReopen?.addEventListener('click', () => setTreeCollapsed(false));
  if (localStorage.getItem('nuni.folderTree.collapsed') === '1') setTreeCollapsed(true);

  mobileToggle?.addEventListener('click', () => explorer.classList.toggle('tree-mobile-open'));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') explorer.classList.remove('tree-mobile-open');
  });

  let resizing = false;
  const savedWidth = Number(localStorage.getItem('nuni.folderTree.width'));
  if (savedWidth >= 210 && savedWidth <= 440) explorer.style.setProperty('--tree-width', `${savedWidth}px`);
  treeResizer?.addEventListener('pointerdown', e => {
    resizing = true;
    treeResizer.setPointerCapture(e.pointerId);
    document.body.classList.add('tree-resizing');
  });
  treeResizer?.addEventListener('pointermove', e => {
    if (!resizing) return;
    const rect = explorer.getBoundingClientRect();
    const width = Math.max(210, Math.min(440, e.clientX - rect.left));
    explorer.style.setProperty('--tree-width', `${width}px`);
    localStorage.setItem('nuni.folderTree.width', String(Math.round(width)));
  });
  treeResizer?.addEventListener('pointerup', () => {
    resizing = false;
    document.body.classList.remove('tree-resizing');
  });

  bindTreeNode(rootNode);
  revealCurrentPath();
})();
