'use strict';

// Standalone contract implementation. Only the action's fixed request adapter
// performs I/O; the injected adapter in tests cannot choose a provider URL.
const CONTRACT = 'drive-metadata-search-v2';
const SCOPE = 'https://www.googleapis.com/auth/drive.metadata.readonly';
const ENDPOINT = 'https://www.googleapis.com/drive/v3/files';
const FIELDS = 'nextPageToken,incompleteSearch,files(id,name,mimeType)';
const MAX_FILES = 20, MAX_PAGES = 5, PAGE_SIZE = 5, MAX_BODY = 65536;
const fail = code => { throw new Error(code); };
const check = (condition, code) => { if (!condition) fail(code); };
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const safeText = (value, limit) => typeof value === 'string' && [...value].length > 0 &&
  [...value].length <= limit && !/[\p{Cc}\p{Cs}]/u.test(value);

function config(value) {
  check(record(value) && Object.keys(value).sort().join(',') === 'folderId,maxFiles,maxPages,policyId,term', 'drive_config_invalid');
  check(typeof value.folderId === 'string' && /^[A-Za-z0-9_-]{5,128}$/.test(value.folderId) &&
    !['root', 'MY_DRIVE', 'UNSET'].includes(value.folderId), 'drive_folder_required');
  check(safeText(value.term, 128) && value.term.trim().length > 0, 'drive_term_invalid');
  check(typeof value.policyId === 'string' && /^[A-Za-z0-9_-]{1,80}$/.test(value.policyId), 'drive_policy_invalid');
  check(Number.isInteger(value.maxFiles) && value.maxFiles > 0 && value.maxFiles <= MAX_FILES &&
    Number.isInteger(value.maxPages) && value.maxPages > 0 && value.maxPages <= MAX_PAGES, 'drive_budget_invalid');
  return Object.freeze({...value});
}

function literal(value) { return value.replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }
function query(value) {
  const v = config(value);
  return `'${literal(v.folderId)}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder' and name contains '${literal(v.term)}'`;
}

function projectFile(file) {
  check(record(file) && Object.keys(file).sort().join(',') === 'id,mimeType,name', 'drive_metadata_fields_invalid');
  check(typeof file.id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(file.id), 'drive_file_id_invalid');
  check(safeText(file.name, 240) && Buffer.byteLength(file.name, 'utf8') <= 512, 'drive_file_name_invalid');
  check(typeof file.mimeType === 'string' && file.mimeType.length <= 127 &&
    /^[A-Za-z0-9.+_-]+\/[A-Za-z0-9.+_-]+$/.test(file.mimeType) &&
    file.mimeType !== 'application/vnd.google-apps.folder', 'drive_mime_invalid');
  return {id: file.id, name: file.name, mimeType: file.mimeType};
}

async function search(input, requestPage) {
  const v = config(input), q = query(v), files = [], ids = new Set(), tokens = new Set();
  check(typeof requestPage === 'function', 'drive_transport_required');
  let pageToken, pagesRead = 0, incompleteSearch = false, truncated = false, stopReason = 'complete';
  while (true) {
    const pageSize = Math.min(PAGE_SIZE, v.maxFiles - files.length);
    const params = {q, fields: FIELDS, spaces: 'drive', corpora: 'user',
      includeItemsFromAllDrives: 'false', supportsAllDrives: 'false', pageSize: String(pageSize)};
    if (pageToken !== undefined) params.pageToken = pageToken;
    let body;
    try { body = await requestPage(Object.freeze(params)); }
    catch { fail('drive_request_failed'); }
    check(record(body) && Object.keys(body).every(k => ['files', 'nextPageToken', 'incompleteSearch'].includes(k)), 'drive_page_invalid');
    check(body.incompleteSearch === undefined || typeof body.incompleteSearch === 'boolean', 'drive_page_invalid');
    const rows = body.files === undefined ? [] : body.files;
    check(Array.isArray(rows) && rows.length <= pageSize, 'drive_page_limit_exceeded');
    const projected = rows.map(projectFile);
    for (const file of projected) {
      check(!ids.has(file.id), 'drive_duplicate_file');
      ids.add(file.id); files.push(file);
    }
    pagesRead++;
    incompleteSearch ||= body.incompleteSearch === true;
    pageToken = body.nextPageToken;
    check(pageToken === undefined || (safeText(pageToken, 2048) && Buffer.byteLength(pageToken) <= 4096), 'drive_page_token_invalid');
    if (pageToken === undefined) break;
    check(!tokens.has(pageToken), 'drive_page_token_loop');
    tokens.add(pageToken);
    if (files.length === v.maxFiles) { truncated = true; stopReason = 'row_limit'; break; }
    if (pagesRead === v.maxPages) { truncated = true; stopReason = 'page_limit'; break; }
  }
  if (!truncated && incompleteSearch) stopReason = 'incomplete_search';
  return {contract: CONTRACT, policyId: v.policyId, complete: !truncated && !incompleteSearch,
    incompleteSearch, truncated, stopReason, pagesRead, rowsRead: files.length, files};
}

function googleRequest(auth, fetchImpl = globalThis.fetch) {
  // Scope evidence is required. Missing or broader scope fails before I/O.
  check(record(auth) && auth.type === 'OAUTH2' && record(auth.data) && auth.scope === SCOPE &&
    typeof auth.access_token === 'string' && auth.access_token.length > 0 && auth.access_token.length <= 8192 &&
    !/[\p{Cc}\p{Cs}]/u.test(auth.access_token), 'drive_connection_scope_invalid');
  check(typeof fetchImpl === 'function', 'drive_fetch_unavailable');
  return async params => {
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 8000);
    try {
      const url = new URL(ENDPOINT); url.search = new URLSearchParams(params).toString();
      const response = await fetchImpl(url, {method: 'GET', headers: {Authorization: 'Bearer ' + auth.access_token,
        Accept: 'application/json'}, redirect: 'error', signal: abort.signal});
      check(response.status === 200 && !response.redirected && response.body &&
        /^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || ''), 'drive_http_failed');
      const reader = response.body.getReader(), chunks = [];
      let size = 0;
      try {
        while (true) {
          const chunk = await reader.read(); if (chunk.done) break;
          size += chunk.value.byteLength;
          check(size <= MAX_BODY, 'drive_body_limit_exceeded'); chunks.push(Buffer.from(chunk.value));
        }
      } finally { await reader.cancel(); }
      return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(Buffer.concat(chunks)));
    } finally { clearTimeout(timer); }
  };
}

module.exports = {CONTRACT, SCOPE, ENDPOINT, FIELDS, MAX_FILES, MAX_PAGES, MAX_BODY, config, query, search, googleRequest};
