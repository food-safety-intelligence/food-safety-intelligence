import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { FeedbackForm } from "@/components/FeedbackForm";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata = {
  title: "Give feedback · Eatelligence Food Safety",
  description:
    "Tell the team about a data error, a listing that looks wrong, or something we could explain more clearly.",
};

// Static export shell. The form is a client component that reads `?venue=`,
// `?name=`, `?source=` and `?role=` from the URL, so it must sit under a
// Suspense boundary (useSearchParams requires one when the page is pre-rendered).
export default function FeedbackPage() {
  return (
    <>
      <SiteHeader activeNav="feedback" />
      <main className="w-full max-w-full lg:max-w-[720px] overflow-x-clip mx-auto px-8 pt-10 pb-24 flex-1">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-xs text-teal hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          Back to search
        </Link>

        <header className="mt-6 mb-8">
          <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">
            Feedback
          </p>
          <h1 className="text-5xl font-light leading-[1.05] tracking-tight">
            Help us make this{" "}
            <span className="serif italic text-teal">better</span>.
          </h1>
          <p className="text-lg text-muted leading-[1.65] mt-5 max-w-[52ch]">
            This is a research preview built on public data. If something looks
            wrong, reads unclearly, or is missing, we want to know. It goes
            straight to the team.
          </p>
        </header>

        <Suspense>
          <FeedbackForm />
        </Suspense>
      </main>
      <SiteFooter />
    </>
  );
}
