"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
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
import { Alert, Button, Card, CardBody, Input, PageHeader, Select, Textarea, useToast } from "@/components/ui";

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
  const [addKind, setAddKind] = useState<SectionKind>("certifications");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        <Card as="section">
          <CardBody className="space-y-4">
            <Input label="Resume name" value={name} onChange={(e) => setName(e.target.value)} hint="Only you see this." />
          </CardBody>
        </Card>

        <Card as="section">
          <CardBody className="space-y-4">
            <h2 className="text-base font-semibold">Contact</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input label="Full name" required value={contact.full_name} onChange={(e) => setContact({ ...contact, full_name: e.target.value })} autoComplete="name" />
              <Input label="Email" type="email" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} autoComplete="email" />
              <Input label="Phone" type="tel" value={contact.phone} onChange={(e) => setContact({ ...contact, phone: e.target.value })} autoComplete="tel" />
              <Input label="Location" value={contact.location} onChange={(e) => setContact({ ...contact, location: e.target.value })} placeholder="City, Country" />
            </div>
            <Textarea label="Links" rows={2} value={linksText} onChange={(e) => setLinksText(e.target.value)} hint="LinkedIn, portfolio, GitHub. One per line." />
          </CardBody>
        </Card>

        {sections.map((s, si) => (
          <Card as="section" key={s.key}>
            <CardBody className="space-y-4">
              <div className="flex items-end gap-2">
                <Input className="flex-1" label={`${KIND_LABEL[s.kind]} section title`} value={s.title} onChange={(e) => updateSection(s.key, (x) => ({ ...x, title: e.target.value }))} />
                <Button size="sm" variant="ghost" aria-label="Move section up" disabled={si === 0} onClick={() => setSections((xs) => move(xs, si, -1))}>
                  <ArrowUp className="h-4 w-4" />
                </Button>
                <Button size="sm" variant="ghost" aria-label="Move section down" disabled={si === sections.length - 1} onClick={() => setSections((xs) => move(xs, si, 1))}>
                  <ArrowDown className="h-4 w-4" />
                </Button>
                <Button size="sm" variant="ghost" aria-label={`Delete ${s.title} section`} onClick={() => setSections((xs) => xs.filter((x) => x.key !== s.key))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>

              <div className="space-y-4">
                {s.items.map((it, ii) => (
                  <div key={ii} className="rounded-md border border-slate-100 bg-slate-50/50 p-4">
                    <ItemEditor kind={s.kind} item={it} onChange={(patch) => updateItem(s.key, ii, patch)} />
                    {s.items.length > 1 && (
                      <div className="mt-3 flex justify-end gap-1">
                        <Button size="sm" variant="ghost" aria-label="Move entry up" disabled={ii === 0} onClick={() => updateSection(s.key, (x) => ({ ...x, items: move(x.items, ii, -1) }))}>
                          <ArrowUp className="h-4 w-4" />
                        </Button>
                        <Button size="sm" variant="ghost" aria-label="Move entry down" disabled={ii === s.items.length - 1} onClick={() => updateSection(s.key, (x) => ({ ...x, items: move(x.items, ii, 1) }))}>
                          <ArrowDown className="h-4 w-4" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => updateSection(s.key, (x) => ({ ...x, items: x.items.filter((_, i) => i !== ii) }))}>
                          <Trash2 className="h-4 w-4" aria-hidden /> Remove entry
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              {s.kind !== "summary" && (
                <Button size="sm" variant="secondary" onClick={() => updateSection(s.key, (x) => ({ ...x, items: [...x.items, blankItem(x.kind)] }))}>
                  <Plus className="h-4 w-4" aria-hidden /> Add {s.kind === "skills" ? "skill group" : "entry"}
                </Button>
              )}
            </CardBody>
          </Card>
        ))}

        <div className="flex flex-wrap items-end gap-2">
          <Select label="Add a section" value={addKind} onChange={(e) => setAddKind(e.target.value as SectionKind)}>
            {(Object.keys(KIND_LABEL) as SectionKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </Select>
          <Button variant="secondary" onClick={() => setSections((xs) => [...xs, section(addKind)])}>
            <Plus className="h-4 w-4" aria-hidden /> Add section
          </Button>
        </div>

        {error && <Alert tone="error">{error}</Alert>}
        <div className="flex gap-3 border-t border-slate-200 pt-6">
          <Button type="submit" loading={busy}>
            Create resume
          </Button>
          <Button variant="ghost" onClick={() => router.back()}>
            Cancel
          </Button>
        </div>
      </div>
    </form>
  );
}

function BulletsEditor({ bullets, onChange, label = "Bullet points" }: { bullets: string[]; onChange: (b: string[]) => void; label?: string }) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{label}</legend>
      {bullets.map((b, i) => (
        <div key={i} className="flex items-start gap-2">
          <Textarea
            className="flex-1"
            rows={2}
            aria-label={`Bullet ${i + 1}`}
            value={b}
            placeholder="What you did, how, and the result. Use real numbers only."
            onChange={(e) => onChange(bullets.map((x, j) => (j === i ? e.target.value : x)))}
          />
          <Button size="sm" variant="ghost" aria-label={`Move bullet ${i + 1} up`} disabled={i === 0} onClick={() => onChange(move(bullets, i, -1))}>
            <ArrowUp className="h-4 w-4" />
          </Button>
          <Button size="sm" variant="ghost" aria-label={`Delete bullet ${i + 1}`} onClick={() => onChange(bullets.filter((_, j) => j !== i))}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button size="sm" variant="ghost" onClick={() => onChange([...bullets, ""])}>
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
        <Textarea className="sm:col-span-2" rows={2} label="Details (optional)" value={it.details} onChange={(e) => onChange({ details: e.target.value })} />
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
          <Input label="Link (optional)" type="url" value={it.link} onChange={(e) => onChange({ link: e.target.value })} />
        </div>
        <Textarea rows={2} label="Description" value={it.description} onChange={(e) => onChange({ description: e.target.value })} />
        <BulletsEditor bullets={it.bullets} onChange={(bullets) => onChange({ bullets })} />
      </div>
    );
  }
  const it = item as TextItem;
  return (
    <Textarea
      rows={kind === "summary" ? 4 : 2}
      label={kind === "summary" ? "Professional summary" : kind === "skills" ? "Skills" : "Text"}
      hint={kind === "skills" ? "Comma separated, e.g. “Python, SQL, Stakeholder management”. Add a group per category." : undefined}
      value={it.text}
      onChange={(e) => onChange({ text: e.target.value })}
    />
  );
}
