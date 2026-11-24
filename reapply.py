#!/usr/bin/env python3
"""Reapply local Claude Code VS Code sidebar patches after an extension update.

Patches:
- Group rows use a Claude-orange tint so they do not blend into sessions.
- Group headers can be dragged to reorder. Sessions stay on the group
  (sessionIds move with the group object).
- A group with a running or waiting session pulses a deeper orange.
  A group with an unread finished session stays deep orange, without motion.
  Idle sessions leave the group on the light tint.
- The model picker changes only the current session. It no longer writes
  the model into ~/.claude/settings.json, which other running sessions watch.
  Each session's pick is kept in globalState "sessionModels" and given back
  when that session is opened again.
- Session rows show the absolute time of the last message.
- The Archived sessions block is hidden. The archive list and transcripts stay.
- Sessions inside a group are ordered by last activity, newest first.
- A session can be dropped anywhere inside a group, not only on its header.
- The context pie no longer sends /compact. It tells you to open a new
  thread and run /handoff.

The Marketplace build is minified and replaced on every update, so this
script retargets the current install by structure, not by old symbol names.

Usage:
    python3 ~/.config/claude-vscode-group-patch/reapply.py

Then in VS Code: Developer: Reload Window.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
EXT_ROOT = HOME / ".vscode/extensions"
STAMP = Path(__file__).with_name("applied-version.txt")
JS_MARKER = "application/x-claude-code-group"
CSS_MARKER = "USER PATCH: session group contrast"
CSS_REORDER = "USER PATCH: group reorder"
CSS_ACTIVITY = "USER PATCH: group activity v2"
HANDOFF_MARKER = "不要压缩，开新线程"

CSS_PATCH = """
/* USER PATCH: session group contrast. Delete this block to restore upstream styles. */
[class*="groupHeader_"] {
  background: color-mix(in srgb, var(--app-claude-orange) 16%, transparent);
  box-shadow: inset 2px 0 0 var(--app-claude-orange);
}
[class*="groupHeader_"]:hover {
  background: color-mix(in srgb, var(--app-claude-orange) 26%, transparent);
}
[class*="groupName_"] {
  color: color-mix(in srgb, var(--app-claude-orange) 78%, var(--app-primary-foreground));
}
[class*="groupChevron_"] {
  color: var(--app-claude-orange);
}

/* USER PATCH: group reorder */
[class*="groupHeader_"][draggable="true"] { cursor: grab; }
[class*="groupHeader_"][draggable="true"]:active { cursor: grabbing; }
[class*="groupHeader_"].reorder-before {
  box-shadow: inset 2px 0 0 var(--app-claude-orange), inset 0 2px 0 var(--app-claude-orange);
}
[class*="groupHeader_"].reorder-after {
  box-shadow: inset 2px 0 0 var(--app-claude-orange), inset 0 -2px 0 var(--app-claude-orange);
}
[class*="groupHeader_"].reorder-into {
  box-shadow: inset 0 0 0 2px var(--app-claude-orange);
}
.group-nest { margin-left: 14px; }

/* USER PATCH: group activity v2. live = running or waiting. done = unread, not running. */
[class*="groupHeader_"].group-done {
  background: color-mix(in srgb, var(--app-claude-orange) 64%, transparent);
  box-shadow: inset 6px 0 0 var(--app-claude-orange);
}
[class*="groupHeader_"].group-done [class*="groupName_"] {
  color: color-mix(in srgb, var(--app-claude-orange) 94%, var(--app-primary-foreground));
}
[class*="groupHeader_"].group-done:hover {
  background: color-mix(in srgb, var(--app-claude-orange) 76%, transparent);
}
[class*="groupHeader_"].group-live {
  background: color-mix(in srgb, var(--app-claude-orange) 48%, transparent);
  box-shadow: inset 4px 0 0 var(--app-claude-orange);
  animation: claude-group-live 1.4s ease-in-out infinite;
}
[class*="groupHeader_"].group-live:hover {
  background: color-mix(in srgb, var(--app-claude-orange) 58%, transparent);
}
@keyframes claude-group-live {
  0%, 100% { background: color-mix(in srgb, var(--app-claude-orange) 32%, transparent); }
  50% { background: color-mix(in srgb, var(--app-claude-orange) 62%, transparent); }
}
@media (prefers-reduced-motion: reduce) {
  [class*="groupHeader_"].group-live { animation: none; }
}
"""


def fail(msg: str) -> None:
    print(f"BLOCKED: {msg}", file=sys.stderr)
    sys.exit(1)


def active_extension() -> Path:
    manifest = EXT_ROOT / "extensions.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text())
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            for entry in data:
                ident = (entry.get("identifier") or {}).get("id", "")
                if ident.lower() == "anthropic.claude-code":
                    rel = entry.get("relativeLocation")
                    if rel:
                        path = EXT_ROOT / rel
                        if path.is_dir():
                            return path
    candidates = sorted(EXT_ROOT.glob("anthropic.claude-code-*"))
    if not candidates:
        fail(f"no anthropic.claude-code extension under {EXT_ROOT}")
    return candidates[-1]


def backup(path: Path) -> None:
    bak = path.with_name(path.name + ".bak-before-group-patch")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"backup {bak.name}")


def patch_css(css_path: Path) -> str:
    text = css_path.read_text(encoding="utf-8")
    if CSS_MARKER in text and CSS_REORDER in text and CSS_ACTIVITY in text:
        return "css already patched"
    backup(css_path)
    if CSS_MARKER in text or CSS_REORDER in text:
        # Partial older patch: drop from the first marker and rewrite both blocks.
        cut = min(i for i in (text.find(CSS_MARKER), text.find(CSS_REORDER)) if i >= 0)
        text = text[:cut].rstrip() + "\n"
    else:
        text = text.rstrip() + "\n"
    css_path.write_text(text + CSS_PATCH, encoding="utf-8")
    return "css patched"


def once(text: str, pattern: re.Pattern[str], label: str) -> re.Match[str]:
    hits = list(pattern.finditer(text))
    if len(hits) != 1:
        fail(f"{label}: expected 1 match, found {len(hits)}")
    return hits[0]


def apply_handoff(text: str) -> str:
    """Point the context pie at /handoff instead of /compact."""
    if HANDOFF_MARKER in text:
        return text
    replacements = (
        (
            "% context used — click to compact",
            "% context used。不要压缩，开新线程并写约300字转接",
        ),
        (
            "% of context remaining until auto-compact.",
            "% of context left。这段对话已经偏长，继续聊会影响准确性。",
        ),
        (
            "Click to compact now.",
            "开一个新线程。转接约300字，写清文件放在哪、主题、限制了哪些材料、下一步怎么接。",
        ),
    )
    for old, new in replacements:
        if text.count(old) != 1:
            fail(f"handoff string not unique: {old}")
        text = text.replace(old, new, 1)
    click = once(
        text,
        re.compile(r'(\w+)=\(\)=>\{(\w+)\("/compact",\[\]\)\}'),
        "compact click",
    )
    old_click = click.group(0)
    if text.count(old_click) != 1:
        fail("compact click is not unique")
    text = text.replace(old_click, old_click.replace('"/compact"', '"/handoff"', 1), 1)
    return text


MAP_RE = re.compile(
    r"(?P<list>\w+)\.grouped\.map\(\(\{group:(?P<g>\w+),items:(?P<it>\w+)\}\)=>k\((?P<frag>\$?\w+),\{children:\[m\((?P<comp>\w+),\{name:(?P=g)\.name,collapsed:(?P=g)\.collapsed,count:(?P=it)\.length,"
    r"isRenaming:(?P<ren>\w+)===(?P=g)\.id,isDropTarget:(?P<drop>\w+)\?\.kind===\"group\"&&(?P=drop)\.groupId===(?P=g)\.id,"
    r"onToggleCollapsed:\(\)=>\{if\(gSkipClick\.current\)\{gSkipClick\.current=!1;return\}(?P<tog>\w+)\((?P=g)\)\},"
    r"onContextMenu:\((?P<ev>\w+)\)=>(?P<menu>\w+)\((?P=ev),(?P=g)\),"
    r"onFinishRename:\((?P=ev)\)=>(?P<fin>\w+)\((?P=g)\.id,(?P=ev)\),onCancelRename:\(\)=>(?P<can>\w+)\(null\),"
    r"onDragOver:\((?P=ev)\)=>\{if\(gDrag\.current\)\{gOver\((?P=ev),(?P=g)\.id\);return\}(?P<over>\w+)\((?P=ev),\{kind:\"group\",groupId:(?P=g)\.id\}\)\},"
    r"onDragLeave:\((?P=ev)\)=>\{if\(gDrag\.current\)\{gLeave\((?P=ev),(?P=g)\.id\);return\}(?P<leave>\w+)\((?P=ev),\{kind:\"group\",groupId:(?P=g)\.id\}\)\},"
    r"onDrop:\((?P=ev)\)=>\{if\(gDrag\.current\)\{gDrop\((?P=ev),(?P=g)\.id\);return\}(?P<dropfn>\w+)\((?P=ev),\{kind:\"group\",groupId:(?P=g)\.id\}\)\},"
    r"draggable:(?P=ren)!==(?P=g)\.id,"
    r"onDragStart:\((?P=ev)\)=>gStart\((?P=ev),(?P=g)\.id\),"
    r"onDragEnd:\(\)=>\{gClear\(\);setTimeout\(\(\)=>\{gSkipClick\.current=!1\},50\)\},"
    r"reorderEdge:gEdge&&gEdge\.id===(?P=g)\.id\?gEdge\.edge:void 0,activity:gTone\((?P=it)\)\}\),"
    r"!(?P=g)\.collapsed&&(?P=it)\.map\((?P<row>\w+)\)\]\},(?P=g)\.id\)\)"
)


def apply_nest(text: str) -> str:
    """Two-level groups. Drop a group on the middle of another to nest it."""
    if '"reorder-into"' in text:
        return text
    old_cls = '${w==="before"?"reorder-before":""} ${w==="after"?"reorder-after":""}'
    new_cls = old_cls + ' ${w==="into"?"reorder-into":""}'
    if text.count(old_cls) != 1:
        fail("reorder class string is not unique")
    text = text.replace(old_cls, new_cls, 1)

    old_zone = 'rc=ue.clientY<Yo.top+Yo.height/2?"before":"after"'
    if text.count(old_zone) != 1:
        fail("group drag zone is not unique")
    text = text.replace(old_zone, "rc=gZone(ue.currentTarget,ue.clientY,Dt)", 1)

    drop_re = re.compile(
        r"function gDrop\(ue,Dt\)\{let Sn=gDrag\.current,Yo=(\w+)\.current;"
        r"if\(!Sn\|\|!Yo\|\|!(\w+)\|\|ue\.dataTransfer\.getData\(\"application/x-claude-code-group\"\)!==Sn\.nonce\)\{gClear\(\);return\}"
        r"ue\.preventDefault\(\),ue\.stopPropagation\(\);let rc=ue\.currentTarget\.getBoundingClientRect\(\),"
        r"rl=ue\.clientY<rc\.top\+rc\.height/2\?\"before\":\"after\",Wa=Yo\.findIndex\(\(Tm\)=>Tm\.id===Sn\.id\);"
        r"if\(gClear\(\),Wa<0\)return;let Lzt=Yo\.slice\(\),\[hNe\]=Lzt\.splice\(Wa,1\),Tzt=Lzt\.findIndex\(\(NU\)=>NU\.id===Dt\);"
        r"if\(Tzt<0\)return;if\(rl===\"after\"\)Tzt\+=1;Lzt\.splice\(Tzt,0,hNe\),\2\(Lzt\)\}"
    )
    drop_m = once(text, drop_re, "group drop")
    groups_ref, updater = drop_m.group(1), drop_m.group(2)
    new_drop = (
        f"function gDrop(ue,Dt){{let Sn=gDrag.current,Yo={groups_ref}.current;"
        f'if(!Sn||!Yo||!{updater}||ue.dataTransfer.getData("application/x-claude-code-group")!==Sn.nonce){{gClear();return}}'
        "ue.preventDefault(),ue.stopPropagation();let rl=gZone(ue.currentTarget,ue.clientY,Dt);gClear();"
        "if(Sn.id===Dt)return;let drag=Yo.find((g)=>g.id===Sn.id),target=Yo.find((g)=>g.id===Dt);"
        "if(!drag||!target)return;let isParent=Yo.some((g)=>g.parentId===drag.id),"
        "targetParent=target.parentId&&Yo.some((g)=>g.id===target.parentId&&!g.parentId)?target.parentId:void 0;"
        f'if(rl==="into"){{if(isParent||targetParent||drag.parentId===target.id)return;'
        f'{updater}(Yo.map((g)=>g.id===drag.id?{{...g,parentId:target.id}}:g));return}}'
        "if(isParent&&targetParent)return;let moved={...drag};"
        "if(targetParent)moved.parentId=targetParent;else delete moved.parentId;"
        "let arr=Yo.filter((g)=>g.id!==drag.id),idx=arr.findIndex((g)=>g.id===target.id);"
        f'if(idx<0)return;if(rl==="after")idx+=1;arr.splice(idx,0,moved),{updater}(arr)}}'
    )
    text = text.replace(drop_m.group(0), new_drop, 1)

    mapped = once(text, MAP_RE, "grouped map")
    d = mapped.groupdict()
    g, it, frag, comp = d["g"], d["it"], d["frag"], d["comp"]
    ren, drop, tog, ev = d["ren"], d["drop"], d["tog"], d["ev"]
    menu, fin, can = d["menu"], d["fin"], d["can"]
    over, leave, dropfn, row = d["over"], d["leave"], d["dropfn"], d["row"]
    text = text.replace(mapped.group(0), f"gRows({d['list']}.grouped)", 1)

    flat_re = re.compile(
        rf"{d['list']}\.grouped\.flatMap\(\(\{{group:{g},items:{it}\}}\)=>{g}\.collapsed\?\[\]:{it}\)"
    )
    flat_m = once(text, flat_re, "grouped keyboard list")
    text = text.replace(
        flat_m.group(0),
        f"{d['list']}.grouped.flatMap(({{group:{g},items:{it}}})=>{g}.collapsed||gHidden({d['list']}.grouped,{g})?[]:{it})",
        1,
    )

    del_m = once(
        text,
        re.compile(r"function (\w+)\(e,t\)\{return e\.filter\(\(n\)=>n\.id!==t\)\}"),
        "delete group helper",
    )
    new_del = (
        f"function {del_m.group(1)}(e,t){{return e.filter((n)=>n.id!==t).map((n)=>{{"
        "if(n.parentId!==t)return n;let c={...n};return delete c.parentId,c})}"
    )
    text = text.replace(del_m.group(0), new_del, 1)

    helpers = (
        f"function gZone(el,y,id){{let rows={groups_ref}.current||[],"
        "drag=gDrag.current&&rows.find((g)=>g.id===gDrag.current.id),t=rows.find((g)=>g.id===id),"
        "blocked=!!(t&&t.parentId)||!!(drag&&rows.some((g)=>g.parentId===drag.id)),"
        "r=el.getBoundingClientRect(),p=(y-r.top)/Math.max(r.height,1);"
        'if(blocked)return p<.5?"before":"after";return p<.2?"before":p>.8?"after":"into"}'
        f"function gHidden(rows,g){{if(!g.parentId)return!1;let p=rows.find((r)=>r.group.id===g.parentId);return!!(p&&p.group.collapsed)}}"
        f"function gHead({g},{it},extra){{return m({comp},{{name:{g}.name,collapsed:{g}.collapsed,count:{it}.length+extra.length,"
        f"isRenaming:{ren}==={g}.id,isDropTarget:{drop}?.kind===\"group\"&&{drop}.groupId==={g}.id,"
        f"onToggleCollapsed:()=>{{if(gSkipClick.current){{gSkipClick.current=!1;return}}{tog}({g})}},"
        f"onContextMenu:({ev})=>{menu}({ev},{g}),"
        f"onFinishRename:({ev})=>{fin}({g}.id,{ev}),onCancelRename:()=>{can}(null),"
        f"onDragOver:({ev})=>{{if(gDrag.current){{gOver({ev},{g}.id);return}}{over}({ev},{{kind:\"group\",groupId:{g}.id}})}},"
        f"onDragLeave:({ev})=>{{if(gDrag.current){{gLeave({ev},{g}.id);return}}{leave}({ev},{{kind:\"group\",groupId:{g}.id}})}},"
        f"onDrop:({ev})=>{{if(gDrag.current){{gDrop({ev},{g}.id);return}}{dropfn}({ev},{{kind:\"group\",groupId:{g}.id}})}},"
        f"draggable:{ren}!=={g}.id,onDragStart:({ev})=>gStart({ev},{g}.id),"
        "onDragEnd:()=>{gClear();setTimeout(()=>{gSkipClick.current=!1},50)},"
        f"reorderEdge:gEdge&&gEdge.id==={g}.id?gEdge.edge:void 0,activity:gTone([...{it},...extra])}})}}"
        f"function gRows(rows){{let top=rows.filter(({{group:g}})=>!g.parentId||!rows.some((r)=>r.group.id===g.parentId)),"
        f"kids=(id)=>rows.filter(({{group:g}})=>g.parentId===id);"
        f"return top.map(({{group:{g},items:{it}}})=>{{let ch=kids({g}.id),extra=ch.flatMap((c)=>c.items);"
        f"return k({frag},{{children:[gHead({g},{it},extra),!{g}.collapsed&&k(\"div\",{{className:\"group-nest\",children:["
        f"ch.map(({{group:cu,items:ci}})=>k({frag},{{children:[gHead(cu,ci,[]),!cu.collapsed&&ci.map({row})]}},cu.id)),"
        f"{it}.map({row})]}})]}},{g}.id)}})}}"
    )
    anchor = "function gTone("
    if text.count(anchor) != 1:
        fail("gTone anchor is not unique")
    text = text.replace(anchor, helpers + anchor, 1)

    return patch_group_schema(text, "webview")


GROUP_SCHEMA_RE = re.compile(
    r"\{id:(\w+)\(\),name:[^{}]*?collapsed:\w+\(\)\.catch\(!1\),"
    r"sessionIds:\w+\(\w+\(\)\)\.default\(\(\)=>\[\]\)\.catch\(\(\)=>\[\]\)"
)
GROUP_DEST_RE = re.compile(
    r"let\{id:l,name:(\w),collapsed:(\w),sessionIds:(\w)\}=a\.data"
)
GROUP_PUSH_RE = re.compile(
    r"t\.push\(\{id:l,name:(\w),collapsed:(\w),sessionIds:(\w)\}\)\}return t\}"
)
PARENT_CLEAN = (
    "let gids=new Set(t.map((g)=>g.id));for(let g of t)if(g.parentId&&!gids.has(g.parentId))g.parentId=void 0;"
    "let used=new Set(t.map((g)=>g.parentId).filter(Boolean));for(let g of t)if(used.has(g.id))g.parentId=void 0;"
    "return t.map((g)=>{let o={id:g.id,name:g.name,collapsed:g.collapsed,sessionIds:g.sessionIds};"
    "if(g.parentId)o.parentId=g.parentId;return o})}"
)


def patch_group_schema(text: str, label: str) -> str:
    """Keep parentId when the group list is parsed and saved."""
    schema = once(text, GROUP_SCHEMA_RE, f"{label} group schema")
    text = text.replace(schema.group(0), schema.group(0) + f",parentId:{schema.group(1)}().optional()", 1)
    dest = once(text, GROUP_DEST_RE, f"{label} group destructure")
    text = text.replace(
        dest.group(0),
        f"let{{id:l,name:{dest.group(1)},collapsed:{dest.group(2)},sessionIds:{dest.group(3)},parentId:pp}}=a.data",
        1,
    )
    push = once(text, GROUP_PUSH_RE, f"{label} group push")
    text = text.replace(
        push.group(0),
        f"t.push({{id:l,name:{push.group(1)},collapsed:{push.group(2)},sessionIds:{push.group(3)},...pp?{{parentId:pp}}:{{}}}})}}"
        + PARENT_CLEAN,
        1,
    )
    return text


def apply_host_parent_store(text: str) -> str:
    """Keep a parentId side copy that the stock extension never rewrites."""
    if "sessionGroupParents:" in text:
        return text
    set_m = once(
        text,
        re.compile(r"async setSessionGroups\((\w)\)\{await this\.context\.globalState\.update\(this\.sessionGroupsKey\(\),\1\)\}"),
        "host setSessionGroups",
    )
    v = set_m.group(1)
    text = text.replace(
        set_m.group(0),
        f"async setSessionGroups({v}){{await this.context.globalState.update(this.sessionGroupsKey(),{v});"
        "let gp={};for(let g of Array.isArray(" + v + ")?" + v + ":[])if(g&&g.parentId)gp[g.id]=g.parentId;"
        'await this.context.globalState.update(this.sessionGroupsKey().replace(/^sessionGroups:/,"sessionGroupParents:"),gp)}',
        1,
    )
    get_m = once(
        text,
        re.compile(r"getSessionGroups\(\)\{return (\$?\w+)\(this\.context\.globalState\.get\(this\.sessionGroupsKey\(\)\)\)\}"),
        "host getSessionGroups",
    )
    parse = get_m.group(1)
    text = text.replace(
        get_m.group(0),
        "getSessionGroups(){let raw=this.context.globalState.get(this.sessionGroupsKey()),"
        'gp=this.context.globalState.get(this.sessionGroupsKey().replace(/^sessionGroups:/,"sessionGroupParents:"))||{};'
        "if(Array.isArray(raw))raw=raw.map((g)=>g&&!g.parentId&&gp[g.id]?{...g,parentId:gp[g.id]}:g);"
        f"return {parse}(raw)}}",
        1,
    )
    return text


def apply_model_per_session(text: str) -> str:
    """Model picker changes only this session. No write to ~/.claude/settings.json."""
    if "/*per-session-model*/" in text:
        return text
    m = once(
        text,
        re.compile(
            r'let (\w)=await this\.writeUserSettingsAndPush\((\w),\{model:(\w)\.value==="default"\?null:\3\.value\}\);'
            r'return\{type:"set_model_response"'
        ),
        "host set_model",
    )
    v, ch, req = m.group(1), m.group(2), m.group(3)
    new = (
        f'let {v}=await this.writeUserSettingsAndPush({ch},{{model:{req}.value==="default"?null:{req}.value}},!0/*per-session-model*/);'
        'return{type:"set_model_response"'
    )
    return text.replace(m.group(0), new, 1)


def apply_model_memory(text: str) -> str:
    """Remember each session's model in globalState and give it back when the session opens."""
    if "gRememberModel(" in text:
        return text
    set_m = once(
        text,
        re.compile(
            r'let \w=await this\.writeUserSettingsAndPush\((\w),\{model:(\w)\.value==="default"\?null:\2\.value\},!0/\*per-session-model\*/\);'
        ),
        "per-session set_model",
    )
    ch, req = set_m.group(1), set_m.group(2)
    text = text.replace(set_m.group(0), set_m.group(0) + f"this.gRememberModel({ch},{req}.value);", 1)

    arrived = once(
        text,
        re.compile(r"sessionIdArrived\((\w),(\w),(\w)\)\{\2\.sessionId=\3,"),
        "sessionIdArrived",
    )
    c, sid = arrived.group(2), arrived.group(3)
    text = text.replace(arrived.group(0), arrived.group(0) + f"this.gFlushModel({c},{sid}),", 1)

    opened = once(
        text,
        re.compile(r"this\.channels\.set\((\w),(\w+)\),this\.pendingChannels\.delete\(\1\),"),
        "channel opened",
    )
    text = text.replace(opened.group(0), opened.group(0) + f"this.gRestoreModel({opened.group(2)}),", 1)

    methods = (
        'gModelStore(){return this.settings.context.globalState}'
        'gSaveModel(sid,m){let st=this.gModelStore(),map={...st.get("sessionModels")||{}};'
        'if(m===null||m===void 0||m==="default")delete map[sid];else map[sid]={model:m,at:Date.now()};'
        'let ks=Object.keys(map);if(ks.length>500){ks.sort((a,b)=>map[a].at-map[b].at);for(let k of ks.slice(0,ks.length-500))delete map[k]}'
        'st.update("sessionModels",map).then(void 0,(x)=>this.logger.warn(`save session model failed: ${x}`))}'
        'gRememberModel(ch,m){let c=this.channels.get(ch);if(!c)return;if(c.sessionId)this.gSaveModel(c.sessionId,m);else c.gPendingModel=m}'
        'gFlushModel(c,sid){if(c.gPendingModel===void 0)return;let m=c.gPendingModel;c.gPendingModel=void 0;this.gSaveModel(sid,m)}'
        'gRestoreModel(c){let sid=c.sessionId;if(!sid)return;let gm=(this.gModelStore().get("sessionModels")||{})[sid];'
        'if(gm&&gm.model)c.query.applyFlagSettings({model:gm.model}).catch((x)=>this.logger.warn(`restore session model failed: ${x}`))}'
    )
    anchor = once(text, re.compile(r"async setModel\(\w,\w\)\{if\(typeof \w!==\"object\""), "host setModel method")
    return text.replace(anchor.group(0), methods + anchor.group(0), 1)


def patch_host(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    updated = text if "parentId:pp" in text else patch_group_schema(text, "host")
    updated = apply_host_parent_store(updated)
    updated = apply_model_per_session(updated)
    updated = apply_model_memory(updated)
    if updated == text:
        return "host already patched"
    write_js(path, updated)
    return "host patched"


def apply_nest_menu(text: str) -> str:
    """Group right-click menu: move into another group, or back to top level."""
    text = text.replace('p<.28?"before":p>.72?"after"', 'p<.2?"before":p>.8?"after"', 1)
    if "function gNestMenu" in text:
        return text
    drop_m = once(
        text,
        re.compile(r"function gDrop\(ue,Dt\)\{let Sn=gDrag\.current,Yo=(\$?\w+)\.current;if\(!Sn\|\|!Yo\|\|!(\$?\w+)\|\|"),
        "group drop for menu",
    )
    groups_ref, updater = drop_m.group(1), drop_m.group(2)
    rename_m = once(
        text,
        re.compile(r'\{label:"Rename group",onSelect:\(\)=>\$?\w+\((\$?\w+)\.id\)\}'),
        "rename group menu item",
    )
    text = text.replace(rename_m.group(0), rename_m.group(0) + f",...gNestMenu({rename_m.group(1)})", 1)
    helper = (
        f"function gNestMenu(g){{let rows={groups_ref}.current||[],items=[];if(!{updater})return items;"
        "let hasKids=rows.some((r)=>r.parentId===g.id);"
        'if(g.parentId)items.push({label:"移到顶层",separatorBefore:!0,'
        f"onSelect:()=>{{let c={groups_ref}.current||[];{updater}(c.map((r)=>{{if(r.id!==g.id)return r;let o={{...r}};return delete o.parentId,o}}))}}}});"
        "if(!hasKids)for(let t of rows){if(t.id===g.id||t.parentId||t.id===g.parentId)continue;"
        "items.push({label:`放入「${t.name}」`,separatorBefore:items.length===0,"
        f"onSelect:()=>{{let c={groups_ref}.current||[];{updater}(c.map((r)=>r.id===g.id?{{...r,parentId:t.id}}:r))}}}})}}"
        "return items}"
    )
    anchor = "function gTone("
    if text.count(anchor) != 1:
        fail("gTone anchor is not unique")
    return text.replace(anchor, helper + anchor, 1)


def apply_session_time(text: str) -> str:
    """Session rows show the absolute time of the last message, not "5m"."""
    if "getFullYear()===n.getFullYear()" in text:
        return text
    m = once(
        text,
        re.compile(
            r"function (\w+)\((\w+)\)\{let \w+=Date\.now\(\)-\2,i=Math\.floor\(\w/1000\),"
            r"o=Math\.floor\(i/60\),r=Math\.floor\(o/60\),s=Math\.floor\(r/24\),"
            r"a=Math\.floor\(s/30\),l=Math\.floor\(s/365\);if\(l>0\)return`\$\{l\}y`;"
            r"if\(a>0\)return`\$\{a\}mo`;if\(s>0\)return`\$\{s\}d`;if\(r>0\)return`\$\{r\}h`;"
            r"if\(o>0\)return`\$\{o\}m`;return\"now\"\}"
        ),
        "relative time formatter",
    )
    name, arg = m.group(1), m.group(2)
    new = (
        f"function {name}({arg}){{if(!Number.isFinite({arg}))return\"\";"
        f"let d=new Date({arg}),p=(x)=>String(x).padStart(2,\"0\"),n=new Date();"
        'return(d.getFullYear()===n.getFullYear()?"":d.getFullYear()+"-")'
        '+p(d.getMonth()+1)+"-"+p(d.getDate())+" "+p(d.getHours())+":"+p(d.getMinutes())}'
    )
    return text.replace(m.group(0), new, 1)


def apply_group_drop_area(text: str) -> str:
    """Drop a session anywhere inside a group, not only on its header."""
    over_pat = "onDragOver:(ev)=>{if(ev.defaultPrevented||gDrag.current)return;"
    drop_pat = "onDrop:(ev)=>{if(ev.defaultPrevented||gDrag.current)return;"
    if over_pat in text:
        text = text.replace(over_pat, over_pat + "ev.stopPropagation();")
        text = text.replace(drop_pat, drop_pat + "ev.stopPropagation();")
        return text
    head = once(
        text,
        re.compile(
            r'onDragOver:\((\w+)\)=>\{if\(gDrag\.current\)\{gOver\(\1,\w+\.id\);return\}'
            r'(\w+)\(\1,\{kind:"group",groupId:\w+\.id\}\)\},'
            r'onDragLeave:\(\1\)=>\{if\(gDrag\.current\)\{gLeave\(\1,\w+\.id\);return\}'
            r'(\w+)\(\1,\{kind:"group",groupId:\w+\.id\}\)\},'
            r'onDrop:\(\1\)=>\{if\(gDrag\.current\)\{gDrop\(\1,\w+\.id\);return\}'
            r'(\w+)\(\1,\{kind:"group",groupId:\w+\.id\}\)\}'
        ),
        "group header session drop handlers",
    )
    over, leave, drop = head.group(2), head.group(3), head.group(4)
    def area(gid):
        return (
            f'onDragOver:(ev)=>{{if(ev.defaultPrevented||gDrag.current)return;ev.stopPropagation();'
            f'{over}(ev,{{kind:"group",groupId:{gid}}})}},'
            f'onDragLeave:(ev)=>{leave}(ev,{{kind:"group",groupId:{gid}}}),'
            f'onDrop:(ev)=>{{if(ev.defaultPrevented||gDrag.current)return;ev.stopPropagation();'
            f'{drop}(ev,{{kind:"group",groupId:{gid}}})}}'
        )
    old_parent = 'k("div",{className:"group-nest",children:['
    if text.count(old_parent) != 1:
        fail("group nest container is not unique")
    text = text.replace(
        old_parent,
        'k("div",{className:"group-nest",' + area("he.id") + ",children:[",
        1,
    )
    old_child = "!cu.collapsed&&ci.map(pN)"
    if text.count(old_child) != 1:
        fail("child session list is not unique")
    text = text.replace(
        old_child,
        '!cu.collapsed&&k("div",{className:"group-nest",' + area("cu.id") + ",children:ci.map(pN)})",
        1,
    )
    return text


def apply_session_sort(text: str) -> str:
    """Sessions inside a group are ordered by last activity, newest first."""
    if "(b.lastModifiedTime.value||0)-(a.lastModifiedTime.value||0)" in text:
        return text
    m = once(
        text,
        re.compile(
            r"return\{grouped:(\w+)\.map\(\((\w+)\)=>\(\{group:\2,items:(\w+)\.get\(\2\.id\)\}\)\)"
        ),
        "grouped items builder",
    )
    groups, g, items = m.group(1), m.group(2), m.group(3)
    new = (
        f"return{{grouped:{groups}.map(({g})=>({{group:{g},"
        f"items:({items}.get({g}.id)||[]).slice().sort((a,b)=>(b.lastModifiedTime.value||0)-(a.lastModifiedTime.value||0))}}))"
    )
    return text.replace(m.group(0), new, 1)


def apply_hide_archived(text: str) -> str:
    """Hide the Archived sessions block. The archive data stays on disk."""
    if "hideArchived" in text:
        return text
    m = once(
        text,
        re.compile(r'(\w+)\.archived\.length>0&&k\('),
        "archived block",
    )
    text = text.replace(
        m.group(0), f"!1/*hideArchived*/&&k(", 1
    )
    flat = once(
        text,
        re.compile(r"\.\.\.(\w+)\?\[\]:(\w+)\.archived\]"),
        "archived keyboard list",
    )
    text = text.replace(flat.group(0), "...[]]", 1)
    return text


def write_js(js_path: Path, text: str) -> None:
    previous = js_path.read_text(encoding="utf-8")
    backup(js_path)
    js_path.write_text(text, encoding="utf-8")
    check = subprocess.run(["node", "--check", str(js_path)], capture_output=True, text=True)
    if check.returncode != 0:
        js_path.write_text(previous, encoding="utf-8")
        fail("node --check failed, restored the previous file:\n" + check.stderr)


def patch_js(js_path: Path) -> str:
    text = js_path.read_text(encoding="utf-8")
    if JS_MARKER in text:
        updated = text if HANDOFF_MARKER in text else apply_handoff(text)
        updated = apply_nest(updated)
        updated = apply_nest_menu(updated)
        updated = apply_session_time(updated)
        updated = apply_group_drop_area(updated)
        updated = apply_session_sort(updated)
        updated = apply_hide_archived(updated)
        if updated == text:
            return "js already patched"
        write_js(js_path, updated)
        return "js nest patched"

    mime_m = once(
        text,
        re.compile(r'var (\w+)="application/x-claude-code-session-rows"'),
        "session mime",
    )
    mime = mime_m.group(1)

    set_at = text.find(f".setData({mime},")
    if set_at < 0:
        fail("session drag setData not found")
    window = text[max(0, set_at - 4000) : set_at]
    hook_hits = list(
        re.finditer(
            r"let (\w+)=(\w+)\(null\),\[(\w+),(\w+)\]=(\w+)\(null\);function (\w+)\(\)\{\1\.current=null,\4\(null\)\}",
            window,
        )
    )
    if len(hook_hits) != 1:
        fail(f"drag state hook: expected 1 match near setData, found {len(hook_hits)}")
    hook = hook_hits[0]
    drag_ref, use_ref, _drop_state, drop_setter, _use_state, clear_fn = hook.groups()
    hook_src = hook.group(0)

    before = window[: hook.start()]
    updater_hits = list(
        re.finditer(
            r"function \w+\(\w+,\w+\)\{let \w+=(\w+)\.current;if\(!\w+\|\|!(\w+)\)return;",
            before,
        )
    )
    if not updater_hits:
        fail("session group updater not found before drag state")
    groups_ref, updater = updater_hits[-1].group(1), updater_hits[-1].group(2)

    image_m = re.search(
        rf"\.setData\({mime},\w+\),\w+\.dataTransfer\.effectAllowed=\"move\",(\w+)\(",
        text,
    )
    if not image_m:
        fail("drag image helper not found")
    drag_image = image_m.group(1)

    comp_m = once(
        text,
        re.compile(
            r"function (\w+)\(\{name:e,collapsed:t,count:n,isRenaming:i=!1,isDropTarget:o=!1,"
            r"onToggleCollapsed:r,onContextMenu:s,onFinishRename:a,onCancelRename:l,"
            r"onDragOver:c,onDragLeave:d,onDrop:u,action:h\}\)\{let p=(\w+)\(null\),f=\2\(!0\);"
        ),
        "group header component",
    )
    comp, _comp_ref = comp_m.group(1), comp_m.group(2)

    btn_m = once(
        text,
        re.compile(
            r"className:`\$\{(\w+)\.groupHeader\} \$\{o\?\1\.dropTarget:\"\"\}`,onClick:i\?void 0:r,"
            r"onContextMenu:i\?void 0:s,onDragEnter:i\?void 0:c,onDragOver:i\?void 0:c,"
            r"onDragLeave:i\?void 0:d,onDrop:i\?void 0:u,"
        ),
        "group header button",
    )
    css_var = btn_m.group(1)

    call_re = re.compile(
        r'm\(' + re.escape(comp) + r',\{name:(?P<g>\w+)\.name,collapsed:(?P=g)\.collapsed,count:(?P<items>\w+)\.length,'
        r'isRenaming:(?P<ren>\w+)===(?P=g)\.id,isDropTarget:(?P<drop>\w+)\?\.kind==="group"&&(?P=drop)\.groupId===(?P=g)\.id,'
        r'onToggleCollapsed:\(\)=>(?P<tog>\w+)\((?P=g)\),onContextMenu:\((?P<ev>\w+)\)=>(?P<menu>\w+)\((?P=ev),(?P=g)\),'
        r'onFinishRename:\((?P=ev)\)=>(?P<fin>\w+)\((?P=g)\.id,(?P=ev)\),onCancelRename:\(\)=>(?P<can>\w+)\(null\),'
        r'onDragOver:\((?P=ev)\)=>(?P<over>\w+)\((?P=ev),\{kind:"group",groupId:(?P=g)\.id\}\),'
        r'onDragLeave:\((?P=ev)\)=>(?P<leave>\w+)\((?P=ev),\{kind:"group",groupId:(?P=g)\.id\}\),'
        r'onDrop:\((?P=ev)\)=>(?P<dropfn>\w+)\((?P=ev),\{kind:"group",groupId:(?P=g)\.id\}\)\}\)'
    )
    call_m = once(text, call_re, "group row call")
    group, _items, renaming, _drop, toggle, ev, menu, finish, cancel, over, leave, drop = call_m.groups()

    status_m = once(
        text,
        re.compile(
            r"(\w+)=at\(\((\w+)\)=>\{if\(!\w+&&!\w+&&!\w+\)return;return \w+\(\w+\(\2,"
        ),
        "session status",
    )
    status_fn = status_m.group(1)

    for name in ("gDrag", "gSkipClick", "gEdge", "setGEdge", "gClear", "gStart", "gOver", "gLeave", "gDrop", "gTone"):
        if re.search(rf"\b{name}\b", text):
            fail(f"injected name {name} already exists; refusing to patch")

    injected = (
        f"let {drag_ref}={use_ref}(null),gDrag={use_ref}(null),gSkipClick={use_ref}(!1),"
        f"[{_drop_state},{drop_setter}]={_use_state}(null),[gEdge,setGEdge]={_use_state}(null);"
        f"function {clear_fn}(){{{drag_ref}.current=null,{drop_setter}(null)}}"
        "function gClear(){gDrag.current=null,setGEdge(null)}"
        f"function gStart(ue,Dt){{if(!{updater}){{ue.preventDefault();return}}"
        "ue.stopPropagation();"
        "let Sn=`g-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,"
        f"Yo={groups_ref}.current?.find((rc)=>rc.id===Dt);"
        'ue.dataTransfer.setData("application/x-claude-code-group",Sn),'
        "ue.dataTransfer.effectAllowed=\"move\",gDrag.current={nonce:Sn,id:Dt},"
        f"gSkipClick.current=!0,{drag_image}(ue.dataTransfer,Yo?.name??\"Group\")}}"
        "function gOver(ue,Dt){let Sn=gDrag.current;"
        'if(!Sn||Sn.id===Dt||!ue.dataTransfer.types.includes("application/x-claude-code-group"))return;'
        "ue.preventDefault(),ue.stopPropagation(),ue.dataTransfer.dropEffect=\"move\";"
        "let Yo=ue.currentTarget.getBoundingClientRect(),"
        'rc=ue.clientY<Yo.top+Yo.height/2?"before":"after";'
        "setGEdge((rl)=>rl&&rl.id===Dt&&rl.edge===rc?rl:{id:Dt,edge:rc})}"
        "function gLeave(ue,Dt){let Sn=ue.currentTarget.getBoundingClientRect();"
        "if(ue.clientX>=Sn.left&&ue.clientX<Sn.right&&ue.clientY>=Sn.top&&ue.clientY<Sn.bottom)return;"
        "setGEdge((Yo)=>Yo&&Yo.id===Dt?null:Yo)}"
        f"function gDrop(ue,Dt){{let Sn=gDrag.current,Yo={groups_ref}.current;"
        f'if(!Sn||!Yo||!{updater}||ue.dataTransfer.getData("application/x-claude-code-group")!==Sn.nonce){{gClear();return}}'
        "ue.preventDefault(),ue.stopPropagation();"
        "let rc=ue.currentTarget.getBoundingClientRect(),"
        'rl=ue.clientY<rc.top+rc.height/2?"before":"after",'
        "Wa=Yo.findIndex((Tm)=>Tm.id===Sn.id);"
        "if(gClear(),Wa<0)return;"
        "let Lzt=Yo.slice(),[hNe]=Lzt.splice(Wa,1),Tzt=Lzt.findIndex((NU)=>NU.id===Dt);"
        f'if(Tzt<0)return;if(rl==="after")Tzt+=1;Lzt.splice(Tzt,0,hNe),{updater}(Lzt)}}'
        f"function gTone(items){{let live=!1,done=!1;for(let s of items){{let x={status_fn}(s);"
        'if(x==="running"||x==="waiting")live=!0;else if(x==="unread")done=!0}'
        'return live?"live":done?"done":void 0}'
    )

    # hook.group(0) was matched inside `window`, whose start is offset. Replace the
    # unique source string in the full file.
    if text.count(hook_src) != 1:
        fail("drag state hook string is not unique in the bundle")
    text = text.replace(hook_src, injected, 1)

    old_sig = (
        "onDragOver:c,onDragLeave:d,onDrop:u,action:h}){let p="
        + _comp_ref
        + "(null),f="
        + _comp_ref
        + "(!0);"
    )
    new_sig = (
        "onDragOver:c,onDragLeave:d,onDrop:u,action:h,draggable:b=!1,onDragStart:_,onDragEnd:x,reorderEdge:w,activity:v}){let p="
        + _comp_ref
        + "(null),f="
        + _comp_ref
        + "(!0);"
    )
    if text.count(old_sig) != 1:
        fail("group header signature is not unique")
    text = text.replace(old_sig, new_sig, 1)

    old_btn = btn_m.group(0)
    new_btn = (
        "className:`${"
        + css_var
        + '.groupHeader} ${o?'
        + css_var
        + '.dropTarget:""} ${w==="before"?"reorder-before":""} ${w==="after"?"reorder-after":""} ${v==="live"?"group-live":""} ${v==="done"?"group-done":""}`,'
        "draggable:b?!0:void 0,onDragStart:b?_:void 0,onDragEnd:b?x:void 0,onClick:i?void 0:r,"
        "onContextMenu:i?void 0:s,onDragEnter:i?void 0:c,onDragOver:i?void 0:c,"
        "onDragLeave:i?void 0:d,onDrop:i?void 0:u,"
    )
    if text.count(old_btn) != 1:
        fail("group header button string is not unique")
    text = text.replace(old_btn, new_btn, 1)

    new_call = (
        f"m({comp},{{name:{group}.name,collapsed:{group}.collapsed,count:{_items}.length,"
        f"isRenaming:{renaming}==={group}.id,isDropTarget:{_drop}?.kind===\"group\"&&{_drop}.groupId==={group}.id,"
        f"onToggleCollapsed:()=>{{if(gSkipClick.current){{gSkipClick.current=!1;return}}{toggle}({group})}},"
        f"onContextMenu:({ev})=>{menu}({ev},{group}),"
        f"onFinishRename:({ev})=>{finish}({group}.id,{ev}),"
        f"onCancelRename:()=>{cancel}(null),"
        f"onDragOver:({ev})=>{{if(gDrag.current){{gOver({ev},{group}.id);return}}{over}({ev},{{kind:\"group\",groupId:{group}.id}})}},"
        f"onDragLeave:({ev})=>{{if(gDrag.current){{gLeave({ev},{group}.id);return}}{leave}({ev},{{kind:\"group\",groupId:{group}.id}})}},"
        f"onDrop:({ev})=>{{if(gDrag.current){{gDrop({ev},{group}.id);return}}{drop}({ev},{{kind:\"group\",groupId:{group}.id}})}},"
        f"draggable:{renaming}!=={group}.id,"
        f"onDragStart:({ev})=>gStart({ev},{group}.id),"
        "onDragEnd:()=>{gClear();setTimeout(()=>{gSkipClick.current=!1},50)},"
        f"reorderEdge:gEdge&&gEdge.id==={group}.id?gEdge.edge:void 0,activity:gTone({_items})}})"
    )
    old_call = call_m.group(0)
    if text.count(old_call) != 1:
        fail("group row call is not unique")
    text = text.replace(old_call, new_call, 1)

    for label, pattern in (
        ("ungrouped header", re.compile(r'name:"Ungrouped",collapsed:[^,]+,count:(\w+)\.ungrouped\.length')),
        ("archived header", re.compile(r'name:"Archived sessions",collapsed:[^,]+,count:(\w+)\.archived\.length')),
    ):
        header = once(text, pattern, label)
        collection = header.group(1)
        field = "ungrouped" if "Ungrouped" in header.group(0) else "archived"
        old_header = header.group(0)
        if text.count(old_header) != 1:
            fail(f"{label} is not unique")
        text = text.replace(old_header, old_header + f",activity:gTone({collection}.{field})", 1)

    text = apply_handoff(text)
    text = apply_nest(text)
    text = apply_nest_menu(text)
    text = apply_session_time(text)
    text = apply_group_drop_area(text)
    text = apply_session_sort(text)
    text = apply_hide_archived(text)

    write_js(js_path, text)
    return (
        "js patched "
        f"(component {comp}, groups {groups_ref}, updater {updater}, dragImage {drag_image})"
    )


def main() -> None:
    ext = active_extension()
    web = ext / "webview"
    js_path = web / "index.js"
    css_path = web / "index.css"
    if not js_path.exists() or not css_path.exists():
        fail(f"webview bundle missing in {ext}")
    print(f"extension {ext.name}")
    print(patch_css(css_path))
    print(patch_js(js_path))
    print(patch_host(ext / "extension.js"))
    STAMP.write_text(ext.name + "\n", encoding="utf-8")
    print("done. Reload the VS Code window.")


if __name__ == "__main__":
    main()
