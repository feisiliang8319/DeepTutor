import AccountShell from "@/components/layout/AccountShell";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";

export default function UtilityLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <AccountShell area="utility">
        <CapabilityGate>{children}</CapabilityGate>
      </AccountShell>
    </CapabilityAccessProvider>
  );
}
