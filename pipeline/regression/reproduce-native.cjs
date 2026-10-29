// Pass a locally reviewed copy of the pinned upstream snippet; never downloads or mutates upstream.
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
function load(type) {
 const window = {location:{pathname:'/thank-you'}, dataLayer:[], history:{}, addEventListener(){}, performance:{getEntriesByType(){return [{type}];}}};
 vm.runInNewContext(source, {window, document:{readyState:'complete'}, setTimeout(fn){fn();}}, {timeout:1000});
 return window.dataLayer.filter(x=>x.event==='thank_you_page_view').length;
}
const result = {source_commit:'0cd9b3a0ef4c411a1d690419ce843f2a1da32cce',initial:load('navigate'),reload:load('reload'),back_forward:load('back_forward'),expected:{initial:1,reload:0,back_forward:0}};
result.defect_reproduced = result.initial === 1 && result.reload === 1 && result.back_forward === 1;
console.log(JSON.stringify(result,null,2));
if (!result.defect_reproduced) process.exitCode=1;
