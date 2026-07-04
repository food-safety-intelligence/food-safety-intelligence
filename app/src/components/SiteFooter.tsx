import { MessageSquarePlus } from "lucide-react";
import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-line bg-cream/70 mt-auto">
      <div className="max-w-[1240px] mx-auto px-8 py-8 grid grid-cols-12 gap-6 items-start text-sm text-muted">
        <div className="col-span-12 md:col-span-5">
          <div className="text-ink font-medium">
            A research preview · UC Berkeley MIDS Capstone
          </div>
          <p className="mt-2 leading-relaxed max-w-[40ch]">
            Open-data project pairing Chicago Food Inspections with 311 and
            license records to estimate forward-window food-safety risk. Not
            affiliated with the City of Chicago.
          </p>
          <Link
            href="/feedback"
            className="mt-3 inline-flex items-center gap-1.5 text-teal hover:underline"
          >
            <MessageSquarePlus className="w-4 h-4" strokeWidth={2} />
            Give feedback
          </Link>
        </div>
        <div className="col-span-6 md:col-span-3">
          <div className="text-2xs tracking-widest uppercase text-muted mb-2">
            Sources
          </div>
          <ul className="space-y-1">
            <li>Chicago Food Inspections</li>
            <li>Chicago 311 Service Requests</li>
            <li>Chicago Business Licenses</li>
          </ul>
        </div>
        <div className="col-span-6 md:col-span-4">
          <div className="text-2xs tracking-widest uppercase text-muted mb-2">
            Team
          </div>
          <p>
            Jun Xu · Arun Agarwal · Bella Davies · Deepak Srivastava · Aurelia
            Yang
          </p>
        </div>
      </div>
    </footer>
  );
}
