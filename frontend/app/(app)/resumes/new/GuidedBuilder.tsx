"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Check, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type {
  CertificationItem,
  EducationItem,
  ExperienceItem,
  GuidedContact,
  GuidedItem,
  GuidedSection,
  ProjectItem,
  SectionKind,
  TextItem,
} from "@/lib/types";
import { Alert, Button, Card, CardBody, IconButton, Input, PageHeader, Section, Textarea, focusRing, useToast } from "@/components/ui";
import { cx } from "@/lib/format";

type Draft = GuidedSection & { key: string };

const KIND_LABEL: Record<SectionKind, string> = {
  summary: "Summary",
  experience: "Experience",
  education: "Education",
  certifications: "Certifications",
  projects: "Projects",
  skills: "Skills",
  achievements: "Achievements",
  other: "Other",
};

function blankItem(kind: SectionKind): GuidedItem {
  switch (kind) {
    case "experience":
      return { company: "", title: "", location: "", start: "", end: "", bullets: [""] } satisfies ExperienceItem;
    case "education":
      return { institution: "", degree: "", field: "", start: "", end: "", details: "" } satisfies EducationItem;
    case "certifications":
      return { name: "", issuer: "", date: "" } satisfies CertificationItem;
    case "projects":
      return { name: "", link: "", description: "", bullets: [] } satisfies ProjectItem;
    default:
      return { text: "" } satisfies TextItem;
  }
}

let keySeq = 0;
const newKey = () => `s${++keySeq}`;
const section = (kind: SectionKind): Draft => ({ key: newKey(), kind, title: KIND_LABEL[kind], items: [blankItem(kind)] });

function move<T>(xs: T[], i: number, d: -1 | 1): T[] {
  const j = i + d;
  if (j < 0 || j >= xs.length) return xs;
  const out = [...xs];
  [out[i], out[j]] = [out[j]!, out[i]!];
  return out;
}

const isBlank = (v: unknown) => v === undefined || v === null || (typeof v === "string" && !v.trim());

/** Strip empty strings and empty bullets so the API only receives real content. */
function clean(s: GuidedSection): GuidedSection {
  const items = s.items
    .map((it) => {
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(it)) {
        if (Array.isArray(v)) out[k] = v.map((x: string) => x.trim()).filter(Boolean);
        else if (!isBlank(v)) out[k] = typeof v === "string" ? v.trim() : v;
      }
      return out as unknown as GuidedItem;
    })
    .filter((it) => Object.values(it).some((v) => (Array.isArray(v) ? v.length > 0 : !isBlank(v))));
  return { kind: s.kind, title: s.title.trim() || KIND_LABEL[s.kind], items };
}

export function GuidedBuilder() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const fromOnboarding = params.get("from") === "onboarding";
  const [name, setName] = useState("My resume");
  const [contact, setContact] = useState<GuidedContact>({ full_name: "", email: "", phone: "", location: "", links: [] });
  const [linksText, setLinksText] = useState("");
  const [sections, setSections] = useState<Draft[]>(() => [section("summary"), section("experience"), section("education"), section("skills")]);
  const [renamingKey, setRenamingKey] = useState<string | null>(null);
  const [focusIdx, setFocusIdx] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (focusIdx === null) return;
    document.getElementById(`sec-${focusIdx}`)?.focus();
    setFocusIdx(null);
  }, [focusIdx]);

  const updateSection = (key: string, fn: (s: Draft) => Draft) => setSections((xs) => xs.map((s) => (s.key === key ? fn(s) : s)));
  const updateItem = (key: string, idx: number, patch: Partial<GuidedItem>) =>
    updateSection(key, (s) => ({ ...s, items: s.items.map((it, i) => (i === idx ? ({ ...it, ...patch } as GuidedItem) : it)) }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!contact.full_name.trim()) return setError("Add your full name in the contact section.");
    const body = {
      name: name.trim() || "My resume",
      contact: {
        ...contact,
        links: linksText
          .split(/[\n,]/)
          .map((l) => l.trim())
          .filter(Boolean),
      },
      sections: sections.map(clean).filter((s) => s.items.length > 0),
    };
    if (body.sections.length === 0) return setError("Add content to at least one section.");
    setBusy(true);
    try {
      const { resume, version } = await api.createGuided(body);
      toast.success("Resume created.");
      router.push(fromOnboarding ? `/onboarding?step=job&version=${version.id}` : `/resumes/${resume.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create the resume.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-3xl">
      <PageHeader title="Build a resume" description="Fill in what applies. Skip anything that doesn't. You can reorder sections." />
      <div className="space-y-6">
        <Card as="section" aria-labelledby="about-you">
          <CardBody className="space-y-5">
            <h2 id="about-you" className="text-lg font-semibold">
              About you
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input label="Full name" required value={contact.full_name} onChange={(e) => setContact({ ...contact, full_name: e.target.value })} autoComplete="name" />
              <Input label="Email" type="email" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} autoComplete="email" />
              <Input label="Phone" type="tel" value={contact.phone} onChange={(e) => setContact({ ...contact, phone: e.target.value })} autoComplete="tel" />
              <Input label="Location" value={contact.location} onChange={(e) => setContact({ ...contact, location: e.target.value })} placeholder="City, Country" />
            </div>
            <Textarea label="Links" autoGrow rows={2} value={linksText} onChange={(e) => setLinksText(e.target.value)} hint="LinkedIn, portfolio, GitHub. One per line." />
            <Input label="Resume name" value={name} onChange={(e) => setName(e.target.value)} hint="Only you see this name." />
          </CardBody>
        </Card>

        {sections.map((s, si) => (
          <Card as="section" key={s.key}>
            <CardBody>
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  {renamingKey === s.key ? (
                    <div className="flex items-center gap-2">
                      <Input
                        className="flex-1"
                        label={`${KIND_LABEL[s.kind]} section title`}
                        value={s.title}
                        autoFocus
                        onChange={(e) => updateSection(s.key, (x) => ({ ...x, title: e.target.value }))}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === "Escape") {
                            e.preventDefault();
                            setRenamingKey(null);
                            setFocusIdx(si);
                          }
                        }}
                      />
                      <IconButton label="Done renaming" size="sm" onClick={() => { setRenamingKey(null); setFocusIdx(si); }}>
                        <Check className="h-4 w-4" aria-hidden />
                      </IconButton>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <h2 id={`sec-${si}`} tabIndex={-1} className={cx("min-w-0 break-words rounded text-lg font-semibold", focusRing)}>
                        {s.title}
                      </h2>
                      <IconButton label="Rename section" size="sm" onClick={() => setRenamingKey(s.key)}>
                        <Pencil className="h-4 w-4" aria-hidden />
                      </IconButton>
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 items-center">
                  <IconButton size="sm" label="Move section up" disabled={si === 0} onClick={() => setSections((xs) => move(xs, si, -1))}>
                    <ArrowUp className="h-4 w-4" aria-hidden />
                  </IconButton>
                  <IconButton size="sm" label="Move section down" disabled={si === sections.length - 1} onClick={() => setSections((xs) => move(xs, si, 1))}>
                    <ArrowDown className="h-4 w-4" aria-hidden />
                  </IconButton>
                  <IconButton size="sm" label={`Delete ${s.title} section`} onClick={() => setSections((xs) => xs.filter((x) => x.key !== s.key))}>
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </IconButton>
                </div>
              </div>

              <div className="mt-4">
                {s.items.map((it, ii) => (
                  <div key={ii} className={cx(ii > 0 && "mt-5 border-t border-line pt-5")}>
                    {s.items.length > 1 && (
                      <div className="mb-3 flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-ink-muted">Entry {ii + 1}</span>
                        <div className="flex items-center">
                          <IconButton size="sm" label={`Move entry ${ii + 1} up`} disabled={ii === 0} onClick={() => updateSection(s.key, (x) => ({ ...x, items: move(x.items, ii, -1) }))}>
                            <ArrowUp className="h-4 w-4" aria-hidden />
                          </IconButton>
                          <IconButton size="sm" label={`Move entry ${ii + 1} down`} disabled={ii === s.items.length - 1} onClick={() => updateSection(s.key, (x) => ({ ...x, items: move(x.items, ii, 1) }))}>
                            <ArrowDown className="h-4 w-4" aria-hidden />
                          </IconButton>
                          <IconButton size="sm" label={`Remove entry ${ii + 1}`} onClick={() => updateSection(s.key, (x) => ({ ...x, items: x.items.filter((_, i) => i !== ii) }))}>
                            <Trash2 className="h-4 w-4" aria-hidden />
                          </IconButton>
                        </div>
                      </div>
                    )}
                    <ItemEditor kind={s.kind} item={it} onChange={(patch) => updateItem(s.key, ii, patch)} />
                  </div>
                ))}
              </div>
              {s.kind !== "summary" && (
                <Button className="mt-5" size="sm" variant="secondary" onClick={() => updateSection(s.key, (x) => ({ ...x, items: [...x.items, blankItem(x.kind)] }))}>
                  <Plus className="h-4 w-4" aria-hidden /> Add {s.kind === "skills" ? "skill group" : "entry"}
                </Button>
              )}
            </CardBody>
          </Card>
        ))}

        <Section title="Add a section" id="add-section">
          <div className="flex flex-wrap gap-2">
            {(Object.keys(KIND_LABEL) as SectionKind[]).map((k) => (
              <Button
                key={k}
                size="sm"
                variant="secondary"
                onClick={() => {
                  setSections((xs) => [...xs, section(k)]);
                  setFocusIdx(sections.length);
                }}
              >
                <Plus className="h-4 w-4" aria-hidden /> {KIND_LABEL[k]}
              </Button>
            ))}
          </div>
        </Section>

        <div className="sticky bottom-20 z-30 space-y-3 md:bottom-4">
          {error && <Alert tone="error">{error}</Alert>}
          <div className="flex gap-3 rounded-xl bg-white p-3 shadow-pop ring-1 ring-slate-900/5">
            <Button type="submit" loading={busy}>
              Create resume
            </Button>
            <Button variant="ghost" onClick={() => router.back()}>
              Cancel
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}

function BulletsEditor({ bullets, onChange, label = "Bullet points" }: { bullets: string[]; onChange: (b: string[]) => void; label?: string }) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2 text-sm font-medium">{label}</legend>
      {bullets.map((b, i) => (
        <div key={i} className="flex items-start gap-1">
          <Textarea
            className="flex-1"
            autoGrow
            rows={1}
            aria-label={`Bullet ${i + 1}`}
            value={b}
            placeholder="What you did, how, and the result. Use real numbers only."
            onChange={(e) => onChange(bullets.map((x, j) => (j === i ? e.target.value : x)))}
          />
          <IconButton label={`Move bullet ${i + 1} up`} size="sm" className="mt-1.5" disabled={i === 0} onClick={() => onChange(move(bullets, i, -1))}>
            <ArrowUp className="h-4 w-4" aria-hidden />
          </IconButton>
          <IconButton label={`Delete bullet ${i + 1}`} size="sm" className="mt-1.5" onClick={() => onChange(bullets.filter((_, j) => j !== i))}>
            <Trash2 className="h-4 w-4" aria-hidden />
          </IconButton>
        </div>
      ))}
      <Button size="sm" variant="soft" onClick={() => onChange([...bullets, ""])}>
        <Plus className="h-4 w-4" aria-hidden /> Add bullet
      </Button>
    </fieldset>
  );
}

function ItemEditor({ kind, item, onChange }: { kind: SectionKind; item: GuidedItem; onChange: (patch: Partial<GuidedItem>) => void }) {
  if (kind === "experience") {
    const it = item as ExperienceItem;
    return (
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Job title" value={it.title} onChange={(e) => onChange({ title: e.target.value })} />
          <Input label="Company" value={it.company} onChange={(e) => onChange({ company: e.target.value })} />
          <Input label="Location" value={it.location} onChange={(e) => onChange({ location: e.target.value })} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Start" placeholder="Mar 2021" value={it.start} onChange={(e) => onChange({ start: e.target.value })} />
            <Input label="End" placeholder="Present" value={it.end} onChange={(e) => onChange({ end: e.target.value })} />
          </div>
        </div>
        <BulletsEditor bullets={it.bullets} onChange={(bullets) => onChange({ bullets })} />
      </div>
    );
  }
  if (kind === "education") {
    const it = item as EducationItem;
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Institution" value={it.institution} onChange={(e) => onChange({ institution: e.target.value })} />
        <Input label="Degree" value={it.degree} onChange={(e) => onChange({ degree: e.target.value })} />
        <Input label="Field of study" value={it.field} onChange={(e) => onChange({ field: e.target.value })} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="Start" value={it.start} onChange={(e) => onChange({ start: e.target.value })} />
          <Input label="End" value={it.end} onChange={(e) => onChange({ end: e.target.value })} />
        </div>
        <Textarea className="sm:col-span-2" autoGrow rows={2} optional label="Details" value={it.details} onChange={(e) => onChange({ details: e.target.value })} />
      </div>
    );
  }
  if (kind === "certifications") {
    const it = item as CertificationItem;
    return (
      <div className="grid gap-3 sm:grid-cols-3">
        <Input label="Certification" value={it.name} onChange={(e) => onChange({ name: e.target.value })} />
        <Input label="Issuer" value={it.issuer} onChange={(e) => onChange({ issuer: e.target.value })} />
        <Input label="Date" value={it.date} onChange={(e) => onChange({ date: e.target.value })} />
      </div>
    );
  }
  if (kind === "projects") {
    const it = item as ProjectItem;
    return (
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Project name" value={it.name} onChange={(e) => onChange({ name: e.target.value })} />
          <Input label="Link" optional type="url" value={it.link} onChange={(e) => onChange({ link: e.target.value })} />
        </div>
        <Textarea autoGrow rows={2} label="Description" value={it.description} onChange={(e) => onChange({ description: e.target.value })} />
        <BulletsEditor bullets={it.bullets} onChange={(bullets) => onChange({ bullets })} />
      </div>
    );
  }
  const it = item as TextItem;
  return (
    <Textarea
      autoGrow
      rows={kind === "summary" ? 4 : 2}
      label={kind === "summary" ? "Professional summary" : kind === "skills" ? "Skills" : "Text"}
      hint={kind === "skills" ? "Comma separated, e.g. “Python, SQL, Stakeholder management”. Add a group per category." : undefined}
      value={it.text}
      onChange={(e) => onChange({ text: e.target.value })}
    />
  );
}
