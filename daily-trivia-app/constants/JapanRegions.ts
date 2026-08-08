export type JapanRegionId =
    | 'hokkaido'
    | 'tohoku'
    | 'kanto'
    | 'chubu'
    | 'kinki'
    | 'chugoku'
    | 'shikoku'
    | 'kyushu-okinawa';

export type JapanRegion = {
    id: JapanRegionId;
    label: string;
    prefectures: string[];
};

export const JAPAN_REGIONS: JapanRegion[] = [
    { id: 'hokkaido', label: '北海道', prefectures: ['北海道'] },
    { id: 'tohoku', label: '東北', prefectures: ['青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県'] },
    { id: 'kanto', label: '関東', prefectures: ['茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県'] },
    { id: 'chubu', label: '中部', prefectures: ['新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県', '岐阜県', '静岡県', '愛知県'] },
    { id: 'kinki', label: '近畿', prefectures: ['三重県', '滋賀県', '京都府', '大阪府', '兵庫県', '奈良県', '和歌山県'] },
    { id: 'chugoku', label: '中国', prefectures: ['鳥取県', '島根県', '岡山県', '広島県', '山口県'] },
    { id: 'shikoku', label: '四国', prefectures: ['徳島県', '香川県', '愛媛県', '高知県'] },
    { id: 'kyushu-okinawa', label: '九州・沖縄', prefectures: ['福岡県', '佐賀県', '長崎県', '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県'] },
];

export const getPrefecturesFromLabel = (prefecture?: string): string[] => {
    if (!prefecture) return [];
    return prefecture
        .split(/[・、,／/]/)
        .map((value) => value.trim())
        .filter(Boolean);
};
