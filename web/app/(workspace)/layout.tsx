import AccountShell from "@/components/layout/AccountShell";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <UnifiedChatProvider>
        <AccountShell area="workspace">
          <CapabilityGate>{children}</CapabilityGate>
        </AccountShell>
      </UnifiedChatProvider>
    </CapabilityAccessProvider>
  );
}
