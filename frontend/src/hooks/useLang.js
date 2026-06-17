import { useState, useEffect, useCallback } from 'react';

const STORAGE_KEY = 'ksp_portal_lang';

export function useLang() {
  const [lang, setLangState] = useState(
    () => localStorage.getItem(STORAGE_KEY) || 'en'
  );

  const setLang = useCallback((newLang) => {
    setLangState(newLang);
    localStorage.setItem(STORAGE_KEY, newLang);
  }, []);

  // Sync lang attribute on document and body
  useEffect(() => {
    document.documentElement.lang = lang;
    document.body.lang = lang;
  }, [lang]);

  // t(enText, knText) returns the right string for the current lang
  const t = useCallback((en, kn) => {
    return lang === 'kn' ? kn : en;
  }, [lang]);

  return { lang, setLang, t };
}
