"""角色管线：原图 -> 双足 T-pose 图 -> 3D 模型 -> 绑骨 -> （可选）动作。
每一步的 task_id 存在 assets/<名字>_state.json，中途失败重跑会跳过已完成的步骤（不重复扣积分）。
用法: python tripo.py <名字> [--anims]      原图放在 assets/<名字>.png
不加 --anims 只做到绑骨：同一套 tripo 骨骼的动作可以在游戏里按骨骼名直接共用，不用每个角色再花钱重定向。
"""
import json, os, sys, time, uuid, urllib.request, urllib.error
from pathlib import Path

BASE = "https://openapi.tripo3d.com/v3"  # 国内站 key；国际站 key 换成 openapi.tripo3d.ai
HERE = Path(__file__).parent
OUT = HERE / "assets"
NAME = sys.argv[1]
STATE = OUT / f"{NAME}_state.json"

# ponytail: 动作每批最多 5 个，两批够做格斗原型；要更多就加一批
ANIM_BATCHES = {
    "a": ["idle", "walk", "box_01", "front_kick_01", "hit_to_head"],
    "b": ["jump", "box_02", "hurt", "defeat_02", "victory_celebration"],
}
POSE_PROMPT = ("Same character with every outfit detail unchanged, standing upright on two legs like a cartoon fighter, "
               "full body, front view, both arms (or flippers) stretched straight out sideways in a T-pose, "
               "eyes open, plain white background")


def key():
    k = os.environ.get("TRIPO_API_KEY")
    env = HERE / ".env"
    if not k and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("TRIPO_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"')
    if not k:
        sys.exit("没有找到 TRIPO_API_KEY（.env 或环境变量）")
    return k


KEY = key()


def call(method, path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')}")
    if res.get("code") != 0:
        sys.exit(f"{method} {path} -> {res}")
    return res["data"]


def upload(path):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
    return call("POST", "/files", raw=body, ctype=f"multipart/form-data; boundary={b}")["file_token"]


def wait(task_id, label):
    while True:
        t = call("GET", f"/tasks/{task_id}")
        print(f"\r[{label}] {t['status']} {t.get('progress', 0)}%   ", end="", flush=True)
        if t["status"] == "success":
            print(f" 用了 {t.get('credits_consumed')} 积分")
            return t["output"]
        if t["status"] in ("failed", "cancelled", "banned"):
            sys.exit(f"\n[{label}] 失败: {t}")
        time.sleep(3)


def fetch(url, dest):
    urllib.request.urlretrieve(url, dest)  # 输出链接 5 分钟过期，拿到就下
    print(f"  -> {dest.relative_to(HERE)}")


def main():
    OUT.mkdir(exist_ok=True)
    bal = call("GET", "/account/balance")["balance"]
    print("Tripo 余额:", bal)
    if bal <= 0:
        sys.exit("余额为 0，先去 Key 所在站点的开发者控制台（developers.tripo3d.com / .ai）充值")
    st =json.loads(STATE.read_text()) if STATE.exists() else {}
    save = lambda: STATE.write_text(json.dumps(st, indent=2))

    def step(name, path, body):
        if name not in st:
            st[name] = call("POST", path, body)["task_id"]
            save()
        return wait(st[name], name)

    if "file" not in st:
        st["file"] = upload(OUT / f"{NAME}.png")
        save()

    out = step("pose", "/generation/image-to-image",
               {"input": st["file"], "template": "t_pose", "prompt": POSE_PROMPT})
    fetch(out["generated_image_url"], OUT / f"{NAME}_tpose.png")

    out = step("model", "/generation/image-to-model",
               {"input": st["pose"], "model": "v3.1-20260211", "face_limit": 20000, "texture_quality": "standard"})
    fetch(out["model_url"], OUT / f"{NAME}_static.glb")

    out = step("check", "/animations/rig-check", {"input": st["model"]})
    print("  rig-check:", out)
    if not out.get("riggable"):
        sys.exit(f"Tripo 判定这个模型不能绑骨，看一下 assets/{NAME}_tpose.png 的姿势")

    # v1.0 骨架才有 box/kick 这些格斗动作
    out = step("rig", "/animations/rig", {"input": st["model"], "rig_type": "biped", "model": "v1.0-20240301"})
    fetch(out["model_url"], OUT / f"{NAME}_rig.glb")
    if "--anims" not in sys.argv:
        return

    for batch, anims in ANIM_BATCHES.items():
        out = step(f"{NAME}_{batch}", "/animations/retarget",
                   {"input": st["rig"], "animations": [f"preset:biped:{a}" for a in anims],
                    "animate_in_place": True, "export_with_geometry": batch == "a"})
        fetch(out["model_url"], OUT / f"{NAME}_{batch}.glb")


if __name__ == "__main__":
    main()
