"""Campaign-only validation; never shipped into the upstream repository."""
import json,os,re,shutil,subprocess,sys,tempfile
from pathlib import Path
text=Path('README.md').read_text()
if sys.argv[1]=='jenqyang':
 lines=[l for l in text.splitlines() if l.startswith('- [LazyMind]')]
 assert len(lines)==1,lines
 assert 'https://github.com/LazyAGI/LazyMind' in lines[0]
 assert 'https://img.shields.io/github/stars/LazyAGI/LazyMind?style=social' in lines[0]
 section=text.split('## Platforms/API\n',1)[1].split('\n## ',1)[0]
 assert lines[0] in section
 with tempfile.TemporaryDirectory() as d:
  p=Path(d);(p/'scripts').mkdir();(p/'site').mkdir()
  for f in ['README.md','scripts/build-site.mjs','site/resources.json']:shutil.copy2(f,p/f)
  env={k:v for k,v in os.environ.items() if k not in ['GITHUB_TOKEN','GH_TOKEN']}
  subprocess.run(['node',str(p/'scripts/build-site.mjs')],check=True,env=env)
  data=json.loads((p/'site/resources.json').read_text());entries=[x for x in data if x['name']=='LazyMind']
  assert len(entries)==1 and entries[0]['category']=='Platforms',entries
  assert entries[0]['url']=='https://github.com/LazyAGI/LazyMind'
  assert entries[0]['description'] and 'img.shields.io' not in entries[0]['description']
  print('Upstream site builder parsed one LazyMind entry in Platforms; cached activity mode, no live catalog refresh.')
else:
 raise SystemExit('Only the validated jenqyang route is supported by this campaign artifact.')
subprocess.run(['git','diff','--check'],check=True)
