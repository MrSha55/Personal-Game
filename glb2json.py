"""Tripo 的 glb -> 网页用的瘦身文件。输出 {"gltf": glTF 描述, "bin": base64 的二进制数据}，
游戏里用 fetch 读回来、拼回 glb 再交给 GLTFLoader.parse。
不用 data: URI / 内嵌图片，是因为 Artifact 页面的 CSP 会拦 fetch('data:…') 和 blob: 请求（本地测不出来）。
用法:
  python glb2json.py in.glb out.json --model   只留模型：去掉动画、法线/金属度贴图（卡通渲染用不到），
                                               底色图缩到 1024 另存为同名 .jpg（游戏里用 TextureLoader 读）
  python glb2json.py in.glb out.json --anims   只留骨骼节点和动画（动作包：同一套 tripo 骨骼按名字套到任何角色上）
"""
import base64, io, json, struct, sys
from PIL import Image

TEX_SIZE = 1024


def main(src, dst, mode):
    b = open(src, 'rb').read()
    jl = struct.unpack_from('<I', b, 12)[0]
    g = json.loads(b[20:20 + jl])
    blob = b[28 + jl:28 + jl + struct.unpack_from('<I', b, 20 + jl)[0]]
    views = g['bufferViews']
    keep_acc = []

    if mode == '--anims':
        for k in ('meshes', 'skins', 'materials', 'textures', 'images', 'samplers'):
            g.pop(k, None)
        for n in g['nodes']:
            n.pop('mesh', None); n.pop('skin', None)
        keep_acc = sorted({i for a in g['animations'] for s in a['samplers'] for i in (s['input'], s['output'])})
    else:
        g.pop('animations', None)
        for m in g['materials']:  # 只留底色贴图
            m.pop('normalTexture', None); m.pop('occlusionTexture', None); m.pop('emissiveTexture', None)
            m.get('pbrMetallicRoughness', {}).pop('metallicRoughnessTexture', None)
        tex = {m['pbrMetallicRoughness'].pop('baseColorTexture')['index'] for m in g['materials']}
        assert len(tex) == 1, 'Tripo 模型应该只有一张底色图'
        v = views[g['images'][g['textures'][tex.pop()]['source']]['bufferView']]
        im = Image.open(io.BytesIO(blob[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']])).convert('RGB')
        im.thumbnail((TEX_SIZE, TEX_SIZE), Image.LANCZOS)
        im.save(dst.rsplit('.', 1)[0] + '.jpg', 'JPEG', quality=86, optimize=True)
        for k in ('textures', 'images', 'samplers'):
            g.pop(k, None)
        used = {s['inverseBindMatrices'] for s in g.get('skins', []) if 'inverseBindMatrices' in s}
        for m in g['meshes']:
            for p in m['primitives']:
                used |= set(p['attributes'].values())
                if 'indices' in p: used.add(p['indices'])
        keep_acc = sorted(used)

    # 按用到的 accessor / 图片重新打包 buffer，没用到的数据全部丢掉
    remap = {old: new for new, old in enumerate(keep_acc)}
    acc, out_views, out = [], [], bytearray()

    def push(data):
        out_views.append({'buffer': 0, 'byteOffset': len(out), 'byteLength': len(data)})
        out.extend(data); out.extend(b'\0' * (-len(out) % 4))
        return len(out_views) - 1

    for old in keep_acc:
        a = dict(g['accessors'][old]); v = views[a['bufferView']]
        start = v.get('byteOffset', 0) + a.pop('byteOffset', 0)
        comp = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}[a['componentType']]
        n = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
        assert not v.get('byteStride') or v['byteStride'] == comp * n, '交错存储的顶点数据没处理'
        a['bufferView'] = push(blob[start:start + a['count'] * comp * n])
        if v.get('target'): out_views[-1]['target'] = v['target']
        acc.append(a)

    def fix(o):
        for k in ('POSITION', 'NORMAL', 'TEXCOORD_0', 'JOINTS_0', 'WEIGHTS_0', 'TANGENT', 'COLOR_0'):
            if k in o: o[k] = remap[o[k]]
    for m in g.get('meshes', []):
        for p in m['primitives']:
            fix(p['attributes'])
            if 'indices' in p: p['indices'] = remap[p['indices']]
    for s in g.get('skins', []):
        if 'inverseBindMatrices' in s: s['inverseBindMatrices'] = remap[s['inverseBindMatrices']]
    for a in g.get('animations', []):
        for s in a['samplers']:
            s['input'], s['output'] = remap[s['input']], remap[s['output']]

    g['accessors'], g['bufferViews'] = acc, out_views
    g['buffers'] = [{'byteLength': len(out)}]  # 没有 uri = 用 glb 自带的二进制块
    json.dump({'gltf': g, 'bin': base64.b64encode(bytes(out)).decode()}, open(dst, 'w'), separators=(',', ':'))
    print(f'{src} -> {dst}  {len(open(dst, "rb").read()) / 1e6:.2f} MB')


if __name__ == '__main__':
    mode = next((a for a in sys.argv[3:] if a in ('--model', '--anims')), None)
    if not mode:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], mode)
