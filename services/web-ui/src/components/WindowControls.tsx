import { useId } from 'react';
import { SOURCES } from '../config';
import { listQuarters, MAX_WINDOW_QUARTERS, quarterCount } from '../lib/quarters';
import { clampWindow, type WindowValue } from '../lib/window';

interface Props {
  value: WindowValue;
  onChange: (value: WindowValue) => void;
  showSource?: boolean;
}

export function WindowControls({ value, onChange, showSource = true }: Props) {
  const id = useId();
  const info = SOURCES[value.source];
  const quarters = listQuarters(info.first, info.last);
  const toOptions = quarters.filter(
    (q) => quarterCount(value.from, q) >= 1 && quarterCount(value.from, q) <= MAX_WINDOW_QUARTERS,
  );

  return (
    <div className="controls">
      {showSource && (
        <fieldset className="field" style={{ border: 'none', padding: 0, margin: 0 }}>
          <legend style={{ padding: 0, marginBottom: 6 }}>Source</legend>
          <div className="segmented">
            {Object.values(SOURCES).map((s) => (
              <label key={s.id}>
                <input
                  type="radio"
                  name={`${id}-source`}
                  value={s.id}
                  checked={value.source === s.id}
                  onChange={() => onChange({ source: s.id, from: s.defaultFrom, to: s.defaultTo })}
                />
                {s.label} {s.media}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <label className="field" htmlFor={`${id}-from`}>
        From quarter
        <select
          id={`${id}-from`}
          className="select"
          value={value.from}
          onChange={(e) => onChange(clampWindow({ ...value, from: e.target.value }))}
        >
          {quarters.map((q) => (
            <option key={q} value={q}>
              {q}
            </option>
          ))}
        </select>
      </label>
      <label className="field" htmlFor={`${id}-to`}>
        To quarter
        <select
          id={`${id}-to`}
          className="select"
          value={value.to}
          onChange={(e) => onChange(clampWindow({ ...value, to: e.target.value }))}
        >
          {toOptions.map((q) => (
            <option key={q} value={q}>
              {q}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
