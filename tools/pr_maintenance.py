"""Apply the explicit, reviewed PR housekeeping plan with the repository CI token."""
import json,pathlib,subprocess,tempfile,sys,os
PLAN=pathlib.Path('docs/maintenance/pr-plan.json')
RESULT=pathlib.Path('docs/maintenance/pr-results.json')
plan=json.loads(PLAN.read_text())
repo=plan['repository']
allowed_slugs = ['3ds', 'draft-backends', 'gb-gbc', 'gba', 'gc-wii', 'modern-consoles', 'n64', 'nds', 'nes', 'ps1', 'ps2', 'ps3', 'psp', 'snes', 'switch', 'vita', 'wii-u', 'xbox', 'xbox360']
assert len(plan["create"]) == 19 and {row["slug"] for row in plan["create"]} == set(allowed_slugs), "Unexpected platform scope; re-review required"
assert repo=='OMGitsMatt45/decomp.wtf' and os.environ['GITHUB_REPOSITORY']==repo
results={'repository':repo,'baseline':plan['base_sha'],'closed':[],'preserved':[],'created':[],'errors':[]}
def gh(*args):
 p=subprocess.run(['gh',*args],text=True,capture_output=True)
 if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip())
 return p.stdout.strip()
def api(path):return json.loads(gh('api',f'repos/{repo}/{path}'))
def save():
 RESULT.parent.mkdir(parents=True,exist_ok=True)
 RESULT.write_text(json.dumps(results,indent=2)+'\n')
def notice(message):print('::notice::'+message.replace('%','%25').replace('\r','%0D').replace('\n','%0A'),flush=True)
try:
 for row in plan['preserve']:
  pr=api('pulls/'+str(row['number']))
  assert pr['head']['sha']==row['expected_head'] and pr['state']=='open', 'Preserved PR changed; re-review required'
  results['preserved'].append({'number':pr['number'],'url':pr['html_url'],'draft':pr['draft']})
  notice('Preserved unfinished PR '+pr['html_url'])
  save()
 for row in plan['close']:
  pr=api('pulls/'+str(row['number']))
  assert pr['head']['sha']==row['expected_head'], 'Obsolete PR changed; re-review required'
  if pr['state']=='open':
   gh('pr','close',str(row['number']),'--repo',repo,'--comment',row['comment'])
  verified=api('pulls/'+str(row['number']))
  assert verified['state']=='closed'
  results['closed'].append({'number':verified['number'],'url':verified['html_url']})
  notice('Closed superseded PR '+verified['html_url'])
  save()
 for row in plan['create']:
  branch=api('git/ref/heads/'+row['head'])
  assert branch['object']['sha']==row['expected_head'], 'Work-plan branch changed; re-review required'
  existing=json.loads(gh('pr','list','--repo',repo,'--head',row['head'],'--base','main','--state','open','--json','number,url,isDraft'))
  if existing:
   assert len(existing)==1 and existing[0]['isDraft'], 'Unexpected existing PR state'
   url=existing[0]['url']
  else:
   with tempfile.TemporaryDirectory() as d:
    body=pathlib.Path(d)/'body.md';body.write_text(row['body'])
    url=gh('pr','create','--repo',repo,'--base','main','--head',row['head'],'--draft','--title',row['title'],'--body-file',str(body)).splitlines()[-1]
  number=int(url.rstrip('/').split('/')[-1])
  verified=api('pulls/'+str(number))
  assert verified['state']=='open' and verified['draft'] and verified['head']['sha']==row['expected_head'] and verified['base']['ref']=='main'
  results['created'].append({'slug':row['slug'],'number':number,'url':url,'head':row['head'],'sha':row['expected_head'],'draft':True})
  notice('Draft work plan: '+row['slug']+' '+url)
  save()
except Exception as e:
 results['errors'].append(str(e))
 print('::error::'+str(e).replace('%','%25').replace('\r','%0D').replace('\n','%0A'),flush=True)
 save()
 sys.exit(1)
notice(f"Housekeeping complete: {len(results['closed'])} closed, {len(results['preserved'])} preserved, {len(results['created'])} draft PRs verified")
