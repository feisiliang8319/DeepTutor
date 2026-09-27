"use client";
import i18n from "i18next";
import { useTranslation } from "react-i18next";
export function useTeachingLocale(){ return useTranslation(); }
export function t(source:string,values:Record<string,unknown>={}){ return String(i18n.t("teaching."+source,{defaultValue:source,...values})); }
