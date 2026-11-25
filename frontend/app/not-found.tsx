import { FileQuestion } from "lucide-react";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-4">
      <EmptyState
        icon={FileQuestion}
        title="Page not found"
        description="The page you were looking for doesn't exist or has moved."
        action={<ButtonLink href="/dashboard">Back to tailored resumes</ButtonLink>}
      />
    </main>
  );
}
