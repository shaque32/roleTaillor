"use client";

import { useState } from "react";
import { Bell, Briefcase, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDate, toDateInput } from "@/lib/format";
import type { Application, ApplicationBody, ApplicationStatus } from "@/lib/types";
import { Alert, Badge, Button, Dialog, EmptyState, Input, PageHeader, Select, SkeletonRows, Textarea, useToast } from "@/components/ui";

const STATUSES: { value: ApplicationStatus; label: string; tone: "neutral" | "blue" | "green" | "amber" | "red" }[] = [
  { value: "saved", label: "Saved", tone: "neutral" },
  { value: "applied", label: "Applied", tone: "blue" },
  { value: "interviewing", label: "Interviewing", tone: "amber" },
  { value: "offered", label: "Offer", tone: "green" },
  { value: "accepted", label: "Accepted", tone: "green" },
  { value: "rejected", label: "Rejected", tone: "red" },
  { value: "withdrawn", label: "Withdrawn", tone: "neutral" },
];
const statusMeta = (s: ApplicationStatus) => STATUSES.find((x) => x.value === s) ?? STATUSES[0]!;

/** Date input (YYYY-MM-DD) to ISO at local noon, so the day never shifts across timezones. */
const fromDateInput = (v: string) => (v ? new Date(`${v}T12:00:00`).toISOString() : null);

export function Applications() {
  const toast = useToast();
  const apps = useResource(() => api.applications());
  const resumes = useResource(() => api.resumes());
  const [editing, setEditing] = useState<Application | "new" | null>(null);
  const [deleting, setDeleting] = useState<Application | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "">("");

  const versionOptions = (resumes.data ?? []).filter((r) => r.latest_version).map((r) => ({ id: r.latest_version!.id, label: `${r.name} (v${r.latest_version!.version_number})` }));
  const versionLabel = (vid?: string | null) => versionOptions.find((o) => o.id === vid)?.label;

  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const body: ApplicationBody = {
      company: String(fd.get("company") ?? "").trim(),
      role_title: String(fd.get("role_title") ?? "").trim(),
      status: String(fd.get("status")) as ApplicationStatus,
      applied_at: fromDateInput(String(fd.get("applied_at") ?? "")),
      reminder_at: fromDateInput(String(fd.get("reminder_at") ?? "")),
      notes: String(fd.get("notes") ?? "").trim() || null,
      resume_version_id: String(fd.get("resume_version_id") ?? "") || null,
    };
    if (!body.company || !body.role_title) return toast.error("Company and role are required.");
    setBusy(true);
    try {
      if (editing === "new") {
        const created = await api.createApplication(body);
        apps.setData((xs) => [created, ...(xs ?? [])]);
      } else if (editing) {
        const updated = await api.updateApplication(editing.id, body);
        apps.setData((xs) => xs?.map((a) => (a.id === editing.id ? { ...a, ...body, ...updated } : a)));
      }
      setEditing(null);
      toast.success("Saved.");
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function quickStatus(a: Application, status: ApplicationStatus) {
    apps.setData((xs) => xs?.map((x) => (x.id === a.id ? { ...x, status } : x)));
    try {
      await api.updateApplication(a.id, { status });
    } catch (err) {
      apps.setData((xs) => xs?.map((x) => (x.id === a.id ? { ...x, status: a.status } : x)));
      toast.error(err);
    }
  }

  async function remove() {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.deleteApplication(deleting.id);
      apps.setData((xs) => xs?.filter((a) => a.id !== deleting.id));
      setDeleting(null);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  const rows = (apps.data ?? []).filter((a) => !statusFilter || a.status === statusFilter);
  const current = editing && editing !== "new" ? editing : null;
  const today = new Date().toISOString().slice(0, 10);

  return (
    <>
      <PageHeader
        title="Applications"
        description="Keep track of where you've applied and which resume you sent."
        actions={
          <Button onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" aria-hidden /> Add application
          </Button>
        }
      />
      {apps.loading && <SkeletonRows />}
      {apps.error && <Alert tone="error">{apps.error.message}</Alert>}
      {apps.data && apps.data.length === 0 && (
        <EmptyState
          icon={Briefcase}
          title="No applications yet"
          description="Log each application to remember which tailored resume you sent and when to follow up."
          action={<Button onClick={() => setEditing("new")}>Add your first application</Button>}
        />
      )}
      {apps.data && apps.data.length > 0 && (
        <>
          <div className="mb-4 max-w-xs">
            <Select aria-label="Filter by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as ApplicationStatus | "")}>
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          </div>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
            {rows.map((a) => {
              const meta = statusMeta(a.status);
              const due = a.reminder_at && a.reminder_at.slice(0, 10) <= today;
              return (
                <li key={a.id} className="flex flex-wrap items-start gap-4 px-5 py-4">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">
                      {a.role_title} <span className="font-normal text-ink-muted">· {a.company}</span>
                    </p>
                    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-muted">
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                      {a.applied_at && <span>Applied {formatDate(a.applied_at)}</span>}
                      {versionLabel(a.resume_version_id) && <span>Resume: {versionLabel(a.resume_version_id)}</span>}
                      {a.reminder_at && (
                        <span className={due ? "inline-flex items-center gap-1 font-medium text-amber-700" : "inline-flex items-center gap-1"}>
                          <Bell className="h-3.5 w-3.5" aria-hidden /> {due ? "Follow up due" : "Reminder"} {formatDate(a.reminder_at)}
                        </span>
                      )}
                    </p>
                    {a.notes && <p className="mt-2 line-clamp-2 text-sm text-ink-muted">{a.notes}</p>}
                  </div>
                  <div className="flex items-center gap-1">
                    <Select aria-label={`Status for ${a.role_title}`} value={a.status} onChange={(e) => quickStatus(a, e.target.value as ApplicationStatus)}>
                      {STATUSES.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </Select>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(a)} aria-label={`Edit ${a.role_title}`}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setDeleting(a)} aria-label={`Delete ${a.role_title}`}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </li>
              );
            })}
            {rows.length === 0 && <li className="px-5 py-8 text-center text-sm text-ink-muted">No applications with this status.</li>}
          </ul>
        </>
      )}

      <Dialog open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Add application" : "Edit application"}>
        <form key={current?.id ?? "new"} onSubmit={save} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Input name="company" label="Company" required defaultValue={current?.company} />
            <Input name="role_title" label="Role" required defaultValue={current?.role_title} />
            <Select name="status" label="Status" defaultValue={current?.status ?? "applied"}>
              {STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
            <Input name="applied_at" type="date" label="Date applied" defaultValue={toDateInput(current?.applied_at) || (editing === "new" ? today : "")} />
            <Select name="resume_version_id" label="Resume version" defaultValue={current?.resume_version_id ?? ""}>
              <option value="">Not set</option>
              {versionOptions.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </Select>
            <Input name="reminder_at" type="date" label="Follow-up reminder" defaultValue={toDateInput(current?.reminder_at)} />
          </div>
          <Textarea name="notes" label="Notes" rows={3} defaultValue={current?.notes ?? ""} />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button type="submit" loading={busy}>
              Save
            </Button>
          </div>
        </form>
      </Dialog>

      <Dialog open={Boolean(deleting)} onClose={() => setDeleting(null)} title="Delete this application?" description="This can't be undone.">
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDeleting(null)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={remove} loading={busy}>
            Delete
          </Button>
        </div>
      </Dialog>
    </>
  );
}
