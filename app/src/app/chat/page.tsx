import { Suspense } from "react";
import { ChatPageBody } from "./ChatPageBody";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata = {
  title: "Chat: Food Safety Chicago",
  description:
    "Conversational search for safe Chicago restaurants powered by the Food Safety AI agent.",
};

export default function ChatPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <SiteHeader activeNav="chat" />
      <main className="flex-1 flex flex-col pt-4 min-h-0">
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
