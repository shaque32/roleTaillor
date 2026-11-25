"use client";

import { useRef, useState } from "react";
import { FileUp } from "lucide-react";
import { api } from "@/lib/api";
import type { ResumeWithVersion } from "@/lib/types";
import { Alert, Button, Input, Textarea } from "@/components/ui";
import { cx } from "@/lib/format";

const ACCEPT = ".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const MAX_BYTES = 10 * 1024 * 1024;
const MIN_TEXT_CHARS = 200;
const MAX_TEXT_CHARS = 50_000;

function validate(file: File): string | null {
  const ok = /\.(docx|pdf)$/i.test(file.name);
  if (!ok) return "Please upload a .docx or .pdf file.";
  if (file.size > MAX_BYTES) return "That file is larger than 10 MB.";
  return null;
}

export function ResumeUpload({ onUploaded, submitLabel = "Upload resume" }: { onUploaded: (r: ResumeWithVersion) => void; submitLabel?: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"file" | "text">("file");
  const [text, setText] = useState("");
  const [textName, setTextName] = useState("");
  // Count code points, not UTF-16 units, so the limits match the backend's.
  const charCount = Array.from(text).length;
  const meaningful = Array.from(text.replace(/\s/g, "")).length;
  const textError = charCount > MAX_TEXT_CHARS ? `That is over the ${MAX_TEXT_CHARS.toLocaleString()} character limit.` : null;
  const textReady = meaningful >= MIN_TEXT_CHARS && !textError;

  function switchMode(next: "file" | "text") {
    setMode(next);
    setError(null);
  }

  async function submitText() {
    if (!textReady) return;
    setBusy(true);
    setError(null);
    try {
      onUploaded(await api.createFromText(text, textName.trim() || "Pasted resume"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save your resume.");
    } finally {
      setBusy(false);
    }
  }

  function pick(f: File | undefined) {
    if (!f) return;
    const err = validate(f);
    setError(err);
    if (err) return;
    setFile(f);
    if (!name) setName(f.name.replace(/\.(docx|pdf)$/i, ""));
  }

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      onUploaded(await api.uploadResume(file, name.trim() || file.name));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  const tabs = [
    { id: "file", label: "Upload a file" },
    { id: "text", label: "Paste text" },
  ] as const;
  const toggle = (
    <div role="group" aria-label="How to add your resume" className="inline-flex rounded-md border border-slate-300 bg-white p-0.5">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          aria-pressed={mode === t.id}
          onClick={() => switchMode(t.id)}
          className={cx(
            "rounded px-3 py-1.5 text-sm font-medium transition-colors",
            mode === t.id ? "bg-brand-50 text-brand-700" : "text-ink-muted hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );

  if (mode === "text") {
    return (
      <div className="space-y-4">
        {toggle}
        <Textarea
          label="Resume text"
          rows={14}
          value={text}
          onChange={(e) => setText(e.target.value)}
          error={textError ?? undefined}
          hint="Paste the full text of your resume. We'll format it with a clean, ATS-friendly template."
          placeholder="Jane Doe&#10;jane@example.com&#10;&#10;EXPERIENCE&#10;…"
        />
        <p className="text-xs text-ink-muted" aria-live="polite">
          {charCount.toLocaleString()} / {MAX_TEXT_CHARS.toLocaleString()} characters
          {meaningful < MIN_TEXT_CHARS && charCount > 0 && ` · add a bit more (at least ${MIN_TEXT_CHARS} non-space characters)`}
        </p>
        <Input label="Resume name" value={textName} onChange={(e) => setTextName(e.target.value)} placeholder="Pasted resume" hint="Only you see this, e.g. “Product Manager – 2026”." />
        {error && <Alert tone="error">{error}</Alert>}
        <Button onClick={submitText} disabled={!textReady} loading={busy}>
          {busy ? "Reading your resume…" : submitLabel}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {toggle}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          pick(e.dataTransfer.files[0]);
        }}
        className={cx(
          "flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
          drag ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-white",
        )}
      >
        <FileUp className="h-8 w-8 text-ink-faint" aria-hidden />
        <p className="mt-3 text-sm text-ink">{file ? file.name : "Drag your resume here"}</p>
        <p className="mt-1 text-xs text-ink-muted">DOCX or PDF, up to 10 MB. DOCX keeps your original formatting best.</p>
        <Button variant="secondary" size="sm" className="mt-4" onClick={() => inputRef.current?.click()}>
          {file ? "Choose another file" : "Browse files"}
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          aria-label="Resume file"
          onChange={(e) => pick(e.target.files?.[0] ?? undefined)}
        />
      </div>
      {file && <Input label="Resume name" value={name} onChange={(e) => setName(e.target.value)} hint="Only you see this, e.g. “Product Manager – 2026”." />}
      {error && <Alert tone="error">{error}</Alert>}
      <Button onClick={submit} disabled={!file} loading={busy}>
        {busy ? "Reading your resume…" : submitLabel}
      </Button>
    </div>
  );
}
