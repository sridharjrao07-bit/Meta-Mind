import { createContext, useContext, useState, useEffect } from 'react';

const ThemeContext = createContext();

export const useTheme = () => useContext(ThemeContext);

const ALLOWED_MODES = ['kids', 'teen', 'adult'];

export const ThemeProvider = ({ children }) => {
  const [mode, setMode] = useState(() => {
    const stored = localStorage.getItem('metamind-mode');
    return ALLOWED_MODES.includes(stored) ? stored : 'adult';
  });

  useEffect(() => {
    const validMode = ALLOWED_MODES.includes(mode) ? mode : 'adult';
    localStorage.setItem('metamind-mode', validMode);
    document.documentElement.setAttribute('data-theme', validMode);
  }, [mode]);

  return (
    <ThemeContext.Provider value={{ mode, setMode }}>
      {children}
    </ThemeContext.Provider>
  );
};
