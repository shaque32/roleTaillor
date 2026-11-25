import type { Metadata } from "next";
import { Resumes } from "./Resumes";

export const metadata: Metadata = { title: "Resumes" };

export default function ResumesPage() {
  return <Resumes />;
}
