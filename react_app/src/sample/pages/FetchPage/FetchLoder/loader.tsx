// React Router ローダー関数を使用したデータフェッチのサンプル
import { requestFetch } from '@/utils/libs/fetch/';

// 型定義
type LoaderReturn<T, U> = {
    response: T;
    error: null;
} | {
    response: null;
    error: U;
};


type LoaderProps = {
    request: Request;
    params: { key: string };
};

// disable-next-line
// export const loader = <T, U>({ request, params }: LoaderProps): Promise<LoaderReturn<T, U>> => {
export const loader = <T, U>({ request, params }: LoaderProps): Promise<T | null> => {
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