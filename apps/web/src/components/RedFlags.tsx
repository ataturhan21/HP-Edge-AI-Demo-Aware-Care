// Red-flag checklist (M05; R15; ADR-003). The approved RF01-RF20 wording, levels and urgent messages from
// content/pathways/general-adult-4/red-flags.json (RF17-RF19: ADR-003 amendment; RF20: amendment 4, #194), verbatim;
// tests/acceptance/test_R15.py fails on any drift.
// The server re-checks every ID and decides the routing; this only asks and displays.
import type { S } from "../api/client";

type Level = "emergency" | "urgent_clinician";
type RedFlagPackage = {
  prompt: string;
  none_label: string;
  messages: Record<Level, string>;
  red_flags: { id: string; level: Level; text: string }[];
};

export const RED_FLAGS: RedFlagPackage = /* reviewed-package:begin */ {
    "prompt": "Do any of these apply to you right now?",
    "none_label": "None of these apply",
    "messages": {
      "emergency": "Call 911 now or go to the nearest emergency department. Do not wait for this consultation.",
      "urgent_clinician": "Contact a clinician or urgent care today. Do not wait for a routine appointment."
    },
    "red_flags": [
      {
        "id": "RF01",
        "level": "emergency",
        "text": "Chest pain or pressure, or pain spreading to the arm, jaw or back, especially with sweating or shortness of breath"
      },
      {
        "id": "RF02",
        "level": "emergency",
        "text": "Sudden face drooping, weakness or numbness of an arm or leg, trouble speaking or understanding, or sudden loss of vision"
      },
      {
        "id": "RF03",
        "level": "emergency",
        "text": "Severe difficulty breathing, or blue or grey lips"
      },
      {
        "id": "RF04",
        "level": "emergency",
        "text": "A sudden, severe headache, the worst you have ever had"
      },
      {
        "id": "RF05",
        "level": "emergency",
        "text": "Fainting or passing out, or new confusion"
      },
      {
        "id": "RF06",
        "level": "emergency",
        "text": "A seizure"
      },
      {
        "id": "RF07",
        "level": "emergency",
        "text": "Swelling of the face, lips or tongue, or throat tightness"
      },
      {
        "id": "RF08",
        "level": "emergency",
        "text": "Vomiting blood, or black, tarry or bloody stools"
      },
      {
        "id": "RF09",
        "level": "emergency",
        "text": "Heavy bleeding that does not stop"
      },
      {
        "id": "RF10",
        "level": "emergency",
        "text": "Sudden or severe pain in the belly"
      },
      {
        "id": "RF11",
        "level": "emergency",
        "text": "Thoughts of suicide, or of harming yourself or someone else"
      },
      {
        "id": "RF12",
        "level": "emergency",
        "text": "Fever with a stiff neck, or with a rash that does not fade when pressed"
      },
      {
        "id": "RF13",
        "level": "emergency",
        "text": "Pregnant, with bleeding or severe pain"
      },
      {
        "id": "RF14",
        "level": "emergency",
        "text": "A serious injury, such as a head injury followed by vomiting or drowsiness, or a possible broken bone"
      },
      {
        "id": "RF15",
        "level": "urgent_clinician",
        "text": "A painful, swollen calf or leg"
      },
      {
        "id": "RF16",
        "level": "urgent_clinician",
        "text": "Fever of 39.5 °C (103 °F) or higher for more than 3 days, or being unable to keep fluids down"
      },
      {
        "id": "RF17",
        "level": "urgent_clinician",
        "text": "Coughing up blood"
      },
      {
        "id": "RF18",
        "level": "urgent_clinician",
        "text": "Skin redness that is spreading, with fever"
      },
      {
        "id": "RF19",
        "level": "emergency",
        "text": "New numbness around the groin, buttocks or inner thighs, or back pain with new difficulty starting to urinate or loss of bladder or bowel control"
      },
      {
        "id": "RF20",
        "level": "emergency",
        "text": "Took too much of a medicine, or swallowed something poisonous"
      }
    ]
  } /* reviewed-package:end */;

// #355 (maintainer decision 2026-10-21): how A03 groups the reviewed signs, by body system, by sign ID. Presentation
// only: the reviewed package above (wording, levels, IDs) is unchanged and the server decides the routing. Within a
// group the signs keep their reviewed order. Every ID belongs to exactly one group (tests/ui/improve-redflags.spec.ts).
export const RED_FLAG_GROUPS: { id: string; title: string; ids: string[] }[] = /* sign-groups:begin */ [
  { "id": "heart", "title": "Heart, breathing and circulation", "ids": ["RF01", "RF03", "RF07", "RF15"] },
  { "id": "brain", "title": "Brain and nerves", "ids": ["RF02", "RF04", "RF05", "RF06", "RF19"] },
  { "id": "bleeding", "title": "Bleeding and belly pain", "ids": ["RF08", "RF09", "RF10", "RF17"] },
  { "id": "fever", "title": "Infection and fever", "ids": ["RF12", "RF16", "RF18"] },
  { "id": "mind", "title": "Mental health and poisoning", "ids": ["RF11", "RF20"] },
  { "id": "injury", "title": "Injury and pregnancy", "ids": ["RF13", "RF14"] }
] /* sign-groups:end */;

/** The reviewed signs under their group headings (RED_FLAG_GROUPS order). */
export function groupedRedFlags() {
  return RED_FLAG_GROUPS.map((g) => ({
    ...g,
    flags: g.ids.map((id) => {
      const flag = RED_FLAGS.red_flags.find((f) => f.id === id);
      if (!flag) throw new Error(`Unknown red flag ${id} in RED_FLAG_GROUPS`);
      return flag;
    }),
  }));
}

export const RED_FLAGS_KIND = "red_flags";

/** The checklist answer: ticked IDs, "none" for none of these apply, or null while unanswered. */
export type RedFlagAnswer = string[] | "none" | null;

export function redFlagContext(answer: Exclude<RedFlagAnswer, null>): S["ConfirmedContextWrite"] {
  return { kind: RED_FLAGS_KIND, value: answer === "none" ? [] : answer, units: null, origin: "user", profile_revision: null };
}

/** The most urgent level among ticked IDs, or null when none is a known red flag. */
export function urgentLevel(ids: readonly string[]): Level | null {
  const levels = RED_FLAGS.red_flags.filter((f) => ids.includes(f.id)).map((f) => f.level);
  if (levels.includes("emergency")) return "emergency";
  return levels.length ? "urgent_clinician" : null;
}

/** How a stored checklist answer reads on review and history screens. */
export function redFlagSummary(value: S["Fact"]["value"]): string {
  if (!Array.isArray(value) || value.length === 0) return RED_FLAGS.none_label;
  return RED_FLAGS.red_flags.filter((f) => value.includes(f.id)).map((f) => f.text).join("; ");
}

export function RedFlagChecklist({ value, onChange, error, announce = true }: {
  value: RedFlagAnswer;
  onChange: (next: RedFlagAnswer) => void;
  error?: boolean;
  /** #342: false when the screen's error summary announces the problem, so it is not announced twice. */
  announce?: boolean;
}) {
  const ticked = Array.isArray(value) ? value : [];
  function toggle(id: string, on: boolean) {
    const next = on ? [...ticked, id] : ticked.filter((t) => t !== id);
    onChange(next.length ? next : null);
  }
  return (
    <fieldset aria-describedby={error ? "red-flags-hint red-flags-error" : "red-flags-hint"} aria-invalid={error || undefined}>
      <legend>{RED_FLAGS.prompt}</legend>
      <span className="hint" id="red-flags-hint">
        Read the signs below. Tick every sign that applies, or choose “{RED_FLAGS.none_label}”. Any ticked sign means you
        should get urgent help instead of continuing here.
      </span>
      {/* #355 (maintainer decision 2026-10-21; replaces the #214 skip link): the exclusive choice comes first, so most
          people answer without scrolling past every sign. It is the first control of the question, so the #342 error
          summary link moves focus to it. The signs stay fully visible below; the reviewed wording and levels are
          unchanged. */}
      <label className="choice choice-exclusive">
        <input type="checkbox" id="red-flags-first" name="red-flags-none" checked={value === "none"}
          onChange={(e) => onChange(e.target.checked ? "none" : null)} />
        {RED_FLAGS.none_label}
      </label>
      {/* #184: the exclusive choice is set apart from the signs. */}
      <p className="choice-divider" aria-hidden="true"><span>or</span></p>
      {/* #355: the signs under short headings by body system (RED_FLAG_GROUPS); each group is a named group. */}
      {groupedRedFlags().map((g) => (
        <div key={g.id} className="sign-group" role="group" aria-labelledby={`red-flags-${g.id}`}>
          <h2 id={`red-flags-${g.id}`} className="sign-group-title">{g.title}</h2>
          {g.flags.map((f) => (
            <label key={f.id} className="choice">
              <input type="checkbox" name="red-flags" value={f.id} checked={ticked.includes(f.id)}
                onChange={(e) => toggle(f.id, e.target.checked)} />
              {f.text}
            </label>
          ))}
        </div>
      ))}
      <p className="choice-feedback" role="status">
        {ticked.length > 0 &&
          `${ticked.length} ${ticked.length === 1 ? "sign" : "signs"} ticked. Continue will take you to urgent help.`}
      </p>
      {error && (
        <span id="red-flags-error" className="field-error" role={announce ? "alert" : undefined}>
          Tick the signs that apply, or choose “{RED_FLAGS.none_label}”.
        </span>
      )}
    </fieldset>
  );
}
