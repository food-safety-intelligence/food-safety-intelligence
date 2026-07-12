import { Suspense } from "react";
import { ChatPageBody } from "./ChatPageBody";
import { BackToSearch } from "@/components/BackToSearch";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata = {
  title: "Chat · Eatelligence Food Safety",
  description:
    "Conversational search for safe Chicago restaurants powered by the Food Safety AI agent.",
};

export default function ChatPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <SiteHeader activeNav="chat" />
      <main className="flex-1 flex flex-col pt-4 min-h-0">
        {/* flex-none so the back link sits above the flex-1 chat area; aligned
            to the chat's max-w-2xl message column. */}
        <div className="flex-none px-4 md:px-8 mb-2">
          <div className="max-w-2xl mx-auto">
            <BackToSearch className="inline-flex items-center gap-2 text-sm text-teal hover:underline" />
          </div>
        </div>
        {/* useSearchParams (in ChatPageBody) needs a Suspense boundary under
            static export. */}
        <Suspense fallback={null}>
          <ChatPageBody />
        </Suspense>
      </main>
      <SiteFooter />
    </div>
  );
}
