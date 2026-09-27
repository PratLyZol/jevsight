import { fmt } from "@/lib/reduce";
import type { SideState } from "@/lib/types";

export default function Compare({ sides }: { sides: SideState[] }) {
  if (sides.length !== 2 || !sides.every((s) => s.result)) return null;
  const [a, b] = sides.map((s) => s.result!);
  const pct = (x: number, y: number) => `${(100 * (y - x) / x).toFixed(0)}%`;
  const same = JSON.stringify([...a.pages_named].sort()) === JSON.stringify([...b.pages_named].sort());
  const tiles: [string, string][] = [
    [pct(a.wall_s, b.wall_s), `wall · ${a.wall_s}s → ${b.wall_s}s`],
    [pct(a.claude_turns, b.claude_turns), `model turns · ${a.claude_turns} → ${b.claude_turns}`],
    [pct(a.input_tokens, b.input_tokens), `input tokens · ${fmt(a.input_tokens)} → ${fmt(b.input_tokens)}`],
    [same ? "same" : "differ", `sources named · ${a.pages_named.length} vs ${b.pages_named.length}`],
  ];
  return (
    <div className="compare">
      {tiles.map(([v, l]) => (
        <div className="tile" key={l}>
          <b>{v}</b>
          <span>
            {sides[1].label} vs {sides[0].label} · {l}
          </span>
        </div>
      ))}
    </div>
  );
}
