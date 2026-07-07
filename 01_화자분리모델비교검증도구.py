"""
화자분리(Speaker Diarization) 모델 비교 검증 도구 (자동 비교 + HTML 리포트 생성)

정답(ground-truth) 화자 수 대비 기존/신규 모델의 화자분리 결과를 자동으로 비교하고,
카드형 HTML 리포트(정렬·카테고리 필터 포함)를 생성합니다.

입력:
  --gt   정답 화자수 CSV (컬럼: video, category, duration_sec, gt_speakers)
  --old  기존 모델 화자분리 결과 JSON 폴더 (파일명 = video 값 + .json)
  --new  신규 모델 화자분리 결과 JSON 폴더 (파일명 = video 값 + .json)
         JSON 포맷 예: {"segments": [{"speaker": "SPEAKER_00", "start": 0.0, "end": 3.2}, ...]}

실행:
  python 01_화자분리모델비교검증도구.py --gt ground_truth.csv --old old_model --new new_model --out report.html
"""

import argparse
import csv
import json
from pathlib import Path


def count_speakers(json_path: Path) -> int:
    """화자분리 결과 JSON에서 고유 화자 수를 자동으로 센다."""
    if not json_path.exists():
        return 0
    data = json.loads(json_path.read_text(encoding="utf-8"))
    segments = data.get("segments", data.get("speakers", []))
    speakers = {seg["speaker"] for seg in segments if "speaker" in seg}
    return len(speakers)


def load_ground_truth(csv_path: Path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({
                "video": r["video"],
                "category": (r.get("category") or "기타").strip() or "기타",
                "duration_sec": int(float(r.get("duration_sec", 0) or 0)),
                "gt": int(r["gt_speakers"]),
            })
    if not rows:
        raise ValueError("ground truth CSV에서 유효한 행을 찾지 못했습니다.")
    return rows


def build_comparison(gt_rows, old_dir: Path, new_dir: Path):
    results = []
    missing = []
    for row in gt_rows:
        video = row["video"]
        old_path = old_dir / f"{video}.json"
        new_path = new_dir / f"{video}.json"
        if not old_path.exists() or not new_path.exists():
            missing.append(video)
        old_count = count_speakers(old_path)
        new_count = count_speakers(new_path)
        results.append({
            **row,
            "old": old_count,
            "new": new_count,
            "old_diff": abs(old_count - row["gt"]),
            "new_diff": abs(new_count - row["gt"]),
        })
    if missing:
        print(f"[경고] 결과 파일을 찾지 못한 영상 {len(missing)}개(화자수 0으로 처리): {', '.join(missing)}")
    return results


def fmt_duration(sec: int) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>화자분리 모델 비교 리포트</title>
<style>
  body {{ font-family: sans-serif; margin: 20px; }}
  .toolbar {{ margin-bottom: 16px; }}
  .toolbar button, .toolbar select {{ margin-right: 8px; padding: 6px 10px; }}
  .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; }}
  .card h3 {{ margin: 0 0 4px 0; font-size: 15px; }}
  .badge {{ color: #666; font-size: 13px; }}
  .summary {{ margin-bottom: 12px; font-weight: bold; }}
</style>
</head>
<body>
<h2>화자분리 모델 비교 리포트</h2>
<div class="summary" id="summary">평균 오차(기존) {old_mae:.2f}명 · 평균 오차(신규) {new_mae:.2f}명 · 영상 {count}개</div>
<div class="toolbar">
  정렬:
  <select id="sortKey">
    <option value="default">기본</option>
    <option value="speakers">화자 수</option>
    <option value="duration">영상 길이</option>
  </select>
  <button id="toggleDir">↓ 오름차순</button>
  <select id="categoryFilter"><option value="all">전체 카테고리</option>{category_options}</select>
</div>
<div id="cards"></div>
<script>
const DATA = {data_json};
let sortKey = "default", ascending = true, category = "all";

function render() {{
  let data = DATA.filter(v => category === "all" || v.category === category);
  if (sortKey === "speakers") data = [...data].sort((a,b) => a.gt - b.gt);
  if (sortKey === "duration") data = [...data].sort((a,b) => a.duration_sec - b.duration_sec);
  if (sortKey !== "default" && !ascending) data = [...data].reverse();

  const container = document.getElementById("cards");
  container.innerHTML = "";
  for (const v of data) {{
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h3>${{v.video}} <span class="badge">(${{v.category}})</span></h3>
      <div class="badge">정답 ${{v.gt}}명 · 기존 ${{v.old}}명(오차 ${{v.old_diff}}) → 신규 ${{v.new}}명(오차 ${{v.new_diff}}) · 길이 ${{v.duration_label}}</div>`;
    container.appendChild(card);
  }}
  const cnt = data.length;
  const oldMae = cnt ? data.reduce((s,v)=>s+v.old_diff,0)/cnt : 0;
  const newMae = cnt ? data.reduce((s,v)=>s+v.new_diff,0)/cnt : 0;
  document.getElementById("summary").textContent =
    `평균 오차(기존) ${{oldMae.toFixed(2)}}명 · 평균 오차(신규) ${{newMae.toFixed(2)}}명 · 영상 ${{cnt}}개`;
}}

document.getElementById("sortKey").addEventListener("change", e => {{ sortKey = e.target.value; render(); }});
document.getElementById("categoryFilter").addEventListener("change", e => {{ category = e.target.value; render(); }});
document.getElementById("toggleDir").addEventListener("click", e => {{
  ascending = !ascending;
  e.target.textContent = ascending ? "↓ 오름차순" : "↑ 내림차순";
  render();
}});
render();
</script>
</body>
</html>
"""


def generate_html(results, out_path: Path):
    for r in results:
        r["duration_label"] = fmt_duration(r["duration_sec"])

    categories = sorted({r["category"] for r in results})
    category_options = "".join(f'<option value="{c}">{c}</option>' for c in categories)

    old_mae = sum(r["old_diff"] for r in results) / len(results) if results else 0
    new_mae = sum(r["new_diff"] for r in results) / len(results) if results else 0

    html = HTML_TEMPLATE.format(
        data_json=json.dumps(results, ensure_ascii=False),
        category_options=category_options,
        old_mae=old_mae,
        new_mae=new_mae,
        count=len(results),
    )
    out_path.write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="화자분리 모델 자동 비교 + HTML 리포트 생성")
    parser.add_argument("--gt", required=True, help="정답 화자수 CSV 경로")
    parser.add_argument("--old", required=True, help="기존 모델 결과 JSON 폴더")
    parser.add_argument("--new", required=True, help="신규 모델 결과 JSON 폴더")
    parser.add_argument("--out", default="diarization_report.html", help="출력 HTML 경로")
    args = parser.parse_args()

    gt_rows = load_ground_truth(Path(args.gt))
    results = build_comparison(gt_rows, Path(args.old), Path(args.new))
    generate_html(results, Path(args.out))
    print(f"리포트 생성 완료: {args.out} ({len(results)}개 영상)")


if __name__ == "__main__":
    main()
