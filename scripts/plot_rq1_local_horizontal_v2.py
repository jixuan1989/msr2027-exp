#!/usr/bin/env python3
"""Draw the already exported local RQ1 case in one-column horizontal panels.

Read saved real nodes, edges, memberships and coordinates. Do not select a new
case, lay out the graph again or run community detection.
"""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import json,hashlib,math,sys,shlex
import argparse
import numpy as np
import pyarrow.parquet as pq
import networkx as nx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.lines import Line2D
from scipy.spatial import ConvexHull
from plot_helpers import portable_metadata

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_INPUT=ROOT/'data/plot/rq1_local'
DEFAULT_OUTPUT=ROOT/'outputs/figures'


def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--data-dir',type=Path,default=DEFAULT_INPUT)
 p.add_argument('--out-dir',type=Path,default=DEFAULT_OUTPUT)
 p.add_argument('--dpi',type=int,default=900)
 args=p.parse_args();args.out_dir.mkdir(parents=True,exist_ok=True)
 files={'nodes':args.data_dir/'local_shared_c40_nodes.parquet','all_edges':args.data_dir/'local_shared_c40_all_edges.parquet','human_edges':args.data_dir/'local_shared_c40_human_edges.parquet'}
 nodes=pq.read_table(files['nodes']).to_pylist()
 lookup={n['node_id']:n for n in nodes}
 pos={n['node_id']:np.array([n['x'],n['y']]) for n in nodes}
 graphs=[]
 for key in ['all_edges','human_edges']:
  g=nx.Graph()
  g.add_nodes_from(n['node_id'] for n in nodes if key=='all_edges' or n['present_human_only'])
  for edge in pq.read_table(files[key]).to_pylist():
   g.add_edge(edge['source'],edge['target'],weight=edge['weight'])
  graphs.append(g)
 human_counts=Counter(n['community_human'] for n in nodes if n['common_human'])
 labels=sorted(human_counts,key=lambda c:(-human_counts[c],c))
 palette=['#2474B7','#E69F00']; colours={c:palette[i] for i,c in enumerate(labels)}
 xy=np.array(list(pos.values()))
 low=xy.min(0)-np.array([.13,.17]); high=xy.max(0)+np.array([.13,.13])
 plt.rcParams.update({'font.family':'DejaVu Serif','font.size':8,'pdf.fonttype':42,'svg.fonttype':'none'})
 fig=plt.figure(figsize=(3.42,1.75),facecolor='white')
 stats={}
 for col,(g,label,key) in enumerate(zip(graphs,['(a) All accounts','(b) Human only'],['all-known','human-only'])):
  ax=fig.add_axes([.015+col*.508,.150,.470,.755])
  groups={}
  for name in g:
   n=lookup[name]
   if n['common_human']:
    c=n['community_all'] if col==0 else n['community_human']
    groups.setdefault(c,[]).append(pos[name])
  for c,pts in groups.items():
   pts=np.array(pts);verts=pts[ConvexHull(pts).vertices];centre=verts.mean(0);verts=centre+1.12*(verts-centre)
   color=palette[0] if col==0 else colours[c]
   ax.add_patch(Polygon(verts,closed=True,facecolor=color,edgecolor=color,alpha=.075,linewidth=.55,zorder=0))
  for u,v,d in g.edges(data=True):
   width=.24+.085*math.log1p(d['weight'])
   ax.plot([pos[u][0],pos[v][0]],[pos[u][1],pos[v][1]],color='#84909b',linewidth=width,alpha=.62,zorder=1)
  for name in g:
   n=lookup[name];x,y=pos[name]
   if n['node_type']=='pull_request':
    ax.scatter([x],[y],s=4.8,marker='s',facecolor='#D2D7DB',edgecolor='#98A2AA',linewidth=.25,zorder=2)
    continue
   human=n['account_type']=='human_user'
   color=palette[0] if col==0 else colours[n['community_human']]
   ax.scatter([x],[y],s=14 if human else 25,marker='o' if human else 'D',facecolor=color,edgecolor='#263746',linewidth=.50 if human else .65,zorder=4)
  ax.set_xlim(low[0],high[0]);ax.set_ylim(low[1],high[1]);ax.set_aspect('equal');ax.set_axis_off()
  center_x=.015+col*.508+.470/2
  fig.text(center_x,.109,label,ha='center',va='center',fontsize=8)
  group_text='1 group (19 humans)' if col==0 else '2 groups (11 + 8 humans)'
  fig.text(center_x,.045,group_text,ha='center',va='center',fontsize=8,color='#526170')
  stats[key]={'nodes':len(g),'edges':g.number_of_edges(),'components':nx.number_connected_components(g),'shown_common_humans':sum(lookup[n]['common_human'] for n in g),'shown_common_human_groups':len(groups),'edge_weight_sum':sum(d['weight'] for _,_,d in g.edges(data=True))}
 legend=[Line2D([],[],marker='o',linestyle='',markerfacecolor=palette[0],markeredgecolor='#263746',markersize=3.8,label='Human'),Line2D([],[],marker='D',linestyle='',markerfacecolor=palette[0],markeredgecolor='#263746',markersize=4.2,label='Bot'),Line2D([],[],marker='s',linestyle='',markerfacecolor='#D2D7DB',markeredgecolor='#98A2AA',markersize=3,label='PR')]
 fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.5,.999),ncol=3,frameon=False,fontsize=8,columnspacing=1.2,handletextpad=.25,borderpad=0)
 base=args.out_dir/'fig_rq1_local_horizontal_v2'
 outputs={}
 for ext in ['png','pdf','svg']:
  target=base.with_suffix('.'+ext);fig.savefig(target,dpi=args.dpi,facecolor='white')
  outputs[ext]={'path':str(target),'sha256':sha(target),'bytes':target.stat().st_size}
 plt.close(fig)
 previous=json.loads((args.data_dir/'fig_rq1_local_account_pr_c40_paper.manifest.json').read_text())
 assert stats==previous['panel_stats'],(stats,previous['panel_stats'])
 manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'command':shlex.join(["python",str(Path(__file__).resolve().relative_to(ROOT)),*sys.argv[1:]]),'inputs':{k:{'path':str(f),'sha256':sha(f)} for k,f in files.items()},'script':{'path':str(Path(__file__).resolve()),'sha256':sha(__file__)},'panel_stats':stats,'figure_inches':[3.42,1.75],'font_pt':8,'dpi':args.dpi,'shared_coordinates':True,'coordinate_source':'Exact saved local nodes x,y; no recalculation, rotation or rearrangement','axis_limits':[low.tolist(),high.tolist()],'aspect':'equal','new_selection':False,'local_reclustering':False,'synthetic_edges':False,'node_or_edge_changes':False,'group_colours':colours,'group_sizes':dict(human_counts),'hulls':'Same convex-envelope rule on displayed shared humans; decorative, not estimated boundaries','panel_statistics_equal_previous':True,'outputs':outputs}
 manifest.update({'legend_position':'top center, above both panels','panel_title_position':'centered below each panel','group_count_position':'second line below each panel title','bot_name_labels':False,'bot_label_leader_lines':False})
 manifest = portable_metadata(manifest, ROOT)
 (args.out_dir/'fig_rq1_local_horizontal_v2.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 (args.out_dir/'fig_rq1_local_horizontal_v2.command.txt').write_text(manifest['command']+'\n')
 print(json.dumps({'panel_stats':stats,'figure_inches':manifest['figure_inches'],'output':outputs['png']['path']},indent=2))

if __name__=='__main__':main()
