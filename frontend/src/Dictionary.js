export const Dictionary = {
  kids: {
    dashboardTitle: "Hero Stats",
    streakLabel: "Login Streak!",
    freezeTokenLabel: "Shields",
    startDebateText: "Challenge Boss",
    modeSelectorText: "Mode: Kids",
    recentMastery: "Recent Badges",
    dueToday: "Bosses to Fight Today",
    explainPrompt: "Explain this to me like I'm 5!",
    rebuttalPrompt: "How will you counter this?",
  },
  teen: {
    dashboardTitle: "Mastery Dashboard",
    streakLabel: "Streak",
    freezeTokenLabel: "Freezes",
    startDebateText: "Prove Me Wrong",
    modeSelectorText: "Mode: Teen",
    recentMastery: "Latest Scores",
    dueToday: "Due Today",
    explainPrompt: "Explain this concept in your own words.",
    rebuttalPrompt: "Defend your claim.",
  },
  adult: {
    dashboardTitle: "Mastery Dashboard",
    streakLabel: "Current Streak",
    freezeTokenLabel: "Freeze Tokens",
    startDebateText: "Start Debate",
    modeSelectorText: "Mode: Adult",
    recentMastery: "Recent Mastery",
    dueToday: "Due for Review Today",
    explainPrompt: "Provide a detailed explanation of the concept.",
    rebuttalPrompt: "Respond to the counterargument.",
  }
};

export const getCopy = (mode, key) => {
  return Dictionary[mode]?.[key] || Dictionary['adult'][key] || key;
};
