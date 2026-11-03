import {build} from 'esbuild';
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {mkdir,readFile,writeFile,copyFile} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const here=dirname(fileURLToPath(import.meta.url)),out=resolve(process.argv[2]||'build/site/vendor');
if(Number(process.versions.node.split('.')[0])<26)throw new Error('Node 26 required');
await mkdir(out,{recursive:true});
const result=await build({entryPoints:[resolve(here,'entry.mjs')],bundle:true,minify:true,format:'esm',platform:'browser',target:'es2022',legalComments:'eof',write:false,metafile:true});
const data=result.outputFiles[0].contents,full=await readFile(resolve(here,'node_modules/tone/build/Tone.js'));
await writeFile(resolve(out,'tone-studio.min.js'),data);
const sha=b=>createHash('sha256').update(b).digest('hex');
const packages=new Set();
for(const name of Object.keys(result.metafile.inputs)){const m=name.match(/node_modules\/((?:@[^/]+\/)?[^/]+)/);if(m)packages.add(m[1])}
const licenses=[];
for(const name of [...packages].sort()){
 const root=resolve(here,'node_modules',name),pkg=JSON.parse(await readFile(resolve(root,'package.json'),'utf8'));
 let license='';for(const candidate of ['LICENSE.md','LICENSE','LICENSE.txt','license','license.md']){try{license=await readFile(resolve(root,candidate),'utf8');break}catch{}}
 if(!license)throw new Error('license missing for '+name);
 licenses.push(name+'@'+pkg.version+' ('+pkg.license+')\n'+license);
}
await writeFile(resolve(out,'tone-studio.LICENSE.txt'),licenses.join('\n\n----------------\n\n'));
const report={schema:'web-ui-audio-build/1',node:process.versions.node,tone:'15.1.22',esbuild:'0.25.12',exports:['Synth','start','now','getContext'],packages:[...packages].sort(),subset:{bytes:data.length,gzip_bytes:gzipSync(data).length,sha256:sha(data)},full_umd:{bytes:full.length,gzip_bytes:gzipSync(full).length,sha256:sha(full)},lock_sha256:sha(await readFile(resolve(here,'package-lock.json')))};
await writeFile(resolve(out,'tone-studio.build.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
