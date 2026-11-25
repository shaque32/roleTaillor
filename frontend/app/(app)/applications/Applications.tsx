"use client";

import { useEffect, useRef, useState } from "react";
import { Bell, Briefcase, Calendar, FileText, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDate, toDateInput } from "@/lib/format";
import type { Application, ApplicationBody, ApplicationStatus } from "@/lib/types";
import { Alert, Badge, Button, Card, Dialog, EmptyState, IconButton, Input, PageHeader, SegmentedControl, Select, SkeletonRows, Textarea, useToast } from "@/components/ui";

const STATUSES: { value: ApplicationStatus; label: string; tone: "neutral" | "blue" | "green" | "amber" | "red" }[] = [
  { value: "saved", label: "Saved", tone: "neutral" },
  { value: "applied", label: "Applied", tone: "blue" },
  { value: "interviewing", label: "Interviewing", tone: "amber" },
  { value: "offered", label: "Offer", tone: "green" },
  { value: "accepted", label: "Accepted", tone: "green" },
  { value: "rejected", label: "Rejected", tone: "red" },
  { value: "withdrawn", label: "Withdrawn", tone: "neutral" },
];

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
  const [errors, setErrors] = useState<{ company?: string; role?: string }>({});
  const companyRef = useRef<HTMLInputElement>(null);
  const roleRef = useRef<HTMLInputElement>(null);

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
    const errs = { company: body.company ? undefined : "Add the company.", role: body.role_title ? undefined : "Add the role." };
    setErrors(errs);
    if (errs.company || errs.role) {
      (errs.company ? companyRef : roleRef).current?.focus();
      return;
    }
    setBusy(true);
    try {
      if (editing === "new") {
        const created = await api.createApplication(body);
        apps.setData((xs) => [created, ...(xs ?? [])]);
      } else if (editing) {
        const updated = await api.updateApplication(editing.id, body);
        apps.setData((xs) => xs?.map((a) => (a.id === editing.id ? { ...a, ...body, ...updated } : a)));
      }
      close();
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

  function close() {
    setErrors({});
    setEditing(null);
  }

  const all = apps.data ?? [];
  const present = STATUSES.filter((st) => all.some((a) => a.status === st.value));
  const filter = present.some((st) => st.value === statusFilter) ? statusFilter : "";
  // Don't let a stale filter re-activate if its status reappears later.
  useEffect(() => {
    if (apps.data && statusFilter && filter === "") setStatusFilter("");
  }, [apps.data, statusFilter, filter]);
  const rows = all.filter((a) => !filter || a.status === filter);
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
      {apps.loading && !apps.data && <SkeletonRows rows={4} />}
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
          <SegmentedControl
            variant="chips"
            size="sm"
            aria-label="Filter by status"
            className="mb-4"
            value={filter === "" ? "all" : filter}
            onChange={(v) => setStatusFilter(v === "all" ? "" : (v as ApplicationStatus))}
            options={[
              { value: "all", label: "All", count: all.length },
              ...present.map((st) => ({ value: st.value as string, label: st.label, count: all.filter((a) => a.status === st.value).length })),
            ]}
          />
          <ul className="space-y-3">
            {rows.map((a) => {
              const due = a.reminder_at && a.reminder_at.slice(0, 10) <= today;
              const resumeLabel = versionLabel(a.resume_version_id);
              return (
                <li key={a.id}>
                  <Card>
                    <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:p-5">
                      <div className="min-w-0 flex-1">
                        <p className="break-words text-base font-medium">{a.role_title}</p>
                        <p className="break-words text-sm text-ink-muted">{a.company}</p>
                        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-muted">
                          {a.applied_at && (
                            <span className="inline-flex items-center gap-1.5">
                              <Calendar className="h-3.5 w-3.5" aria-hidden /> Applied {formatDate(a.applied_at)}
                            </span>
                          )}
                          {resumeLabel && (
                            <span className="inline-flex items-center gap-1.5">
                              <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden /> {resumeLabel}
                            </span>
                          )}
                          {a.reminder_at &&
                            (due ? (
                              <Badge tone="amber">
                                <Bell className="h-3 w-3" aria-hidden /> Follow up due {formatDate(a.reminder_at)}
                              </Badge>
                            ) : (
                              <span className="inline-flex items-center gap-1.5">
                                <Bell className="h-3.5 w-3.5" aria-hidden /> Reminder {formatDate(a.reminder_at)}
                              </span>
                            ))}
                        </div>
                        {a.notes && <p className="mt-2 line-clamp-2 text-sm text-ink-muted">{a.notes}</p>}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <Select
                          variant="pill"
                          size="sm"
                          aria-label={`Status for ${a.role_title}`}
                          value={a.status}
                          onChange={(st) => quickStatus(a, st)}
                          options={STATUSES.map((st) => ({ value: st.value, label: st.label, tone: st.tone }))}
                        />
                        <IconButton size="sm" label={`Edit ${a.role_title}`} onClick={() => setEditing(a)}>
                          <Pencil className="h-4 w-4" aria-hidden />
                        </IconButton>
                        <IconButton size="sm" label={`Delete ${a.role_title}`} onClick={() => setDeleting(a)}>
                          <Trash2 className="h-4 w-4" aria-hidden />
                        </IconButton>
                      </div>
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <Dialog open={editing !== null} onClose={close} size="lg" title={editing === "new" ? "Add application" : "Edit application"}>
        <form key={current?.id ?? "new"} onSubmit={save} noValidate className="space-y-5">
          <div className="grid gap-5 sm:grid-cols-2">
            <Input ref={companyRef} name="company" label="Company" required defaultValue={current?.company} error={errors.company} />
            <Input ref={roleRef} name="role_title" label="Role" required defaultValue={current?.role_title} error={errors.role} />
            <Select
              name="status"
              label="Status"
              defaultValue={current?.status ?? "applied"}
              options={STATUSES.map((st) => ({ value: st.value, label: st.label, tone: st.tone }))}
            />
            <Select
              name="resume_version_id"
              label="Resume sent"
              defaultValue={current?.resume_version_id ?? ""}
              options={[{ value: "", label: "Not set" }, ...versionOptions.map((o) => ({ value: o.id, label: o.label }))]}
            />
            <Input name="applied_at" type="date" label="Date applied" defaultValue={toDateInput(current?.applied_at) || (editing === "new" ? today : "")} />
            <Input name="reminder_at" type="date" label="Remind me to follow up" optional defaultValue={toDateInput(current?.reminder_at)} />
          </div>
          <Textarea name="notes" label="Notes" optional autoGrow rows={3} defaultValue={current?.notes ?? ""} />
          <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" loading={busy}>
              Save
            </Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={Boolean(deleting)}
        onClose={() => setDeleting(null)}
        size="sm"
        title="Delete this application?"
        description="This can't be undone."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={remove} loading={busy}>
              Delete
            </Button>
          </>
        }
      />
    </>
  );
}
