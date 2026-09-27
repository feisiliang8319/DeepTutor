"use client";

import { useAuthStatus } from "@/hooks/useAuthStatus";
import TeachingModels from "@/components/teaching/TeachingModels";
import SettingsSectionGrid from "@/components/settings/SettingsSectionGrid";

export default function ModelsSettingsPage() {
  const { productMode, loading } = useAuthStatus();
  if (loading) return null;
  return productMode === "teaching" ? <TeachingModels/> : <SettingsSectionGrid categoryKey="models" />;
}
