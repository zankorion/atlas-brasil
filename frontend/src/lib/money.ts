"use client";
import { useSyncExternalStore } from "react";
import type { Money } from "./api";

// Escolha global de como exibir valores monetários (reais nominais, reais corrigidos pelo IPCA, dólares ou
// gramas de ouro). Vale para o site inteiro e é lembrada neste navegador.
const KEY = "atlas.moeda";
const EVENT = "atlas:moeda";

function read(): Money {
  try {
    const v = localStorage.getItem(KEY);
    return v === "ipca" ? true : v === "usd" || v === "ouro" ? v : false;
  } catch {
    return false;
  }
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export function setMoney(v: Money) {
  try {
    localStorage.setItem(KEY, v === true ? "ipca" : v === false ? "" : v);
  } catch {}
  window.dispatchEvent(new Event(EVENT));
}

/** [opção atual, função para trocar]. No servidor (pré-renderização) vale sempre "nominal". */
export function useMoney(): [Money, (v: Money) => void] {
  return [useSyncExternalStore(subscribe, read, () => false), setMoney];
}
