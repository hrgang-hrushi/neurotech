export type NavTab = 'Dashboard' | 'Investment' | 'Card' | 'Savings' | 'Activity' | 'Settings';

export type Timeframe = '1D' | '1W' | '1M' | '3M' | '1Y' | 'All';

export interface WatchlistStock {
  symbol: string;
  name: string;
  price: string;
  change: string;
  isPositive: boolean;
  marketCap: string;
  peRatio: string;
  high52w: string;
  low52w: string;
  sparkline: {
    d: string;
    dotX: number;
    dotY: number;
  };
  logo: 'apple' | 'meta' | 'amazon' | 'microsoft' | 'google' | 'nvidia' | 'tesla' | 'netflix';
}

export interface AllocationItem {
  id: string;
  name: string;
  percentage: number;
  amount: string;
  color: string;
  textColor: string;
}

export interface TimeframeData {
  timeframe: Timeframe;
  portfolioValue: string;
  changePercentage: string;
  isPositive: boolean;
  mayAugTooltip?: {
    startDate: string;
    startVal: string;
    endDate: string;
    endVal: string;
    gain: string;
  };
  points: { x: number; y: number; label: string; value: string }[];
}

export interface NewsInsight {
  id: string;
  publisher: 'B' | 'CNBC' | 'MW' | 'Reuters' | 'FT';
  headline: string;
  boldPhrase: string;
  fullArticle: string;
  timeAgo: string;
}

export interface NotificationItem {
  id: string;
  title: string;
  message: string;
  time: string;
  read: boolean;
  type: 'dividend' | 'alert' | 'rebalance' | 'security';
}
