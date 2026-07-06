const MEAL_LABELS = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐'
};

function mealLabel(value) {
  return MEAL_LABELS[value] || value || '';
}

function kcal(value) {
  const number = Number(value || 0);
  return `${Math.round(number)} kcal`;
}

function grams(value) {
  const number = Number(value || 0);
  return `${Math.round(number * 10) / 10} g`;
}

function pct(value, total) {
  const n = Number(value || 0);
  const t = Number(total || 0);
  if (!t || t <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((n / t) * 100)));
}

function todayKey() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function compactDate(value) {
  if (!value || typeof value !== 'string') return '';
  return value.slice(5);
}

module.exports = {
  MEAL_LABELS,
  mealLabel,
  kcal,
  grams,
  pct,
  todayKey,
  compactDate
};
