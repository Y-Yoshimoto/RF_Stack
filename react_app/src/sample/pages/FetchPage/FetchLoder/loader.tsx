// React Router ローダー関数を使用したデータフェッチのサンプル
import { requestFetch } from '@/utils/libs/FetchComponents/';

// 型定義
type LoaderProps = {
    request: Request;
    params: { key: string };
};

export const loader = <T,>({ request, params }: LoaderProps): Promise<T | null> => {
    const key = params.key;
    console.debug(request, params);

    return requestFetch({ url: `/static.json?key=${key}` }).then((data) => {
        if (data && typeof data === 'object' && !Array.isArray(data)) {
            return { ...data, params: key };
        }
        return null;
    });
};

export default loader;