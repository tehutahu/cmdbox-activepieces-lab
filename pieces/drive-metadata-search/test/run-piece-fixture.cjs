'use strict';
// Runs the actual bundled framework action, not a reimplementation.
// All Google responses are local fixtures; any native fetch is forbidden.
const fs = require('node:fs');
require('node:net').Socket.prototype.connect = () => { throw Error('Fixture forbids real sockets'); };
require('node:tls').connect = () => { throw Error('Fixture forbids TLS sockets'); };
const {createRequire} = require('node:module');
const {CONTRACT,SCOPE,ENDPOINT,FIELDS,query} = require('../src/search.cjs');
const input = JSON.parse(fs.readFileSync(0,'utf8'));
if (!['A','B'].includes(input.label) || Object.keys(input).sort().join(',') !== 'bundle,label') throw Error('Fixture input invalid');
const requireBundle = createRequire(input.bundle);
const piece = requireBundle(input.bundle).driveMetadataSearch;
const action = piece.getAction('search_folder_metadata');
const fixed = {folderId:'DUMMY_FOLDER_'+input.label, term:'CMDBOX_LAB_ONLY',policyId:'DUMMY-METADATA-POLICY-'+input.label,maxFiles:20,maxPages:5};
const records = [
  {id:input.label+'_ONLY_SYNTHETIC_FILE',name:'CMDBOX_LAB_ONLY_'+input.label+'.txt',mimeType:'text/plain',parent:fixed.folderId,trashed:false},
  {id:'OTHER_FOLDER_FILE',name:'CMDBOX_LAB_ONLY_OTHER.txt',mimeType:'text/plain',parent:'DUMMY_OTHER_FOLDER',trashed:false},
  {id:'TRASHED_FILE',name:'CMDBOX_LAB_ONLY_TRASH.txt',mimeType:'text/plain',parent:fixed.folderId,trashed:true},
  {id:'NESTED_FILE',name:'CMDBOX_LAB_ONLY_NESTED.txt',mimeType:'text/plain',parent:'DUMMY_NESTED_FOLDER',trashed:false},
  {id:'FOLDER_FILE',name:'CMDBOX_LAB_ONLY_FOLDER',mimeType:'application/vnd.google-apps.folder',parent:fixed.folderId,trashed:false},
];
const requests=[];
globalThis.fetch = async (url,options) => {
  if (url.origin+url.pathname !== ENDPOINT || options.method !== 'GET' || options.redirect !== 'error' ||
    url.searchParams.get('q') !== query(fixed) || url.searchParams.get('fields') !== FIELDS ||
    options.headers.Authorization !== 'Bearer LITERAL-DUMMY-GOOGLE-'+input.label ||
    url.searchParams.get('includeItemsFromAllDrives') !== 'false') throw Error('Fixture request refused');
  requests.push({pageSize:Number(url.searchParams.get('pageSize')),hasPageToken:url.searchParams.has('pageToken')});
  if (input.label==='A' && requests.length===1)
    return new Response(JSON.stringify({nextPageToken:'LITERAL-DUMMY-NEXT'}),{headers:{'content-type':'application/json'}});
  if (input.label==='A' && url.searchParams.get('pageToken') !== 'LITERAL-DUMMY-NEXT') throw Error('Continuation required');
  const files = records.filter(x=>x.parent===fixed.folderId && !x.trashed && x.mimeType!=='application/vnd.google-apps.folder')
    .map(({id,name,mimeType})=>({id,name,mimeType}));
  return new Response(JSON.stringify({files,incompleteSearch:input.label==='B'}),{headers:{'content-type':'application/json'}});
};
const auth={type:'OAUTH2',access_token:'LITERAL-DUMMY-GOOGLE-'+input.label,scope:SCOPE,data:{}};
action.run({propsValue:{...fixed,auth},auth})
  .then(result=>{if(result.contract!==CONTRACT) throw Error('Contract mismatch'); console.log(JSON.stringify({result,requests}));})
  .catch(()=>{console.error('Local bundled action fixture failed'); process.exitCode=1;});
