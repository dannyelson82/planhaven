import { createContext, useContext } from 'react'

export type Run = <T>(action: () => Promise<T>) => Promise<T>

export const StepUpContext = createContext<Run>((action) => action())

/** Run an action; if the server asks for a fresh second factor, prompt and retry once. */
export function useStepUp(): Run {
  return useContext(StepUpContext)
}
