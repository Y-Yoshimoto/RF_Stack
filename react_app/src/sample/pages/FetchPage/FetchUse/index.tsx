// use: React API
// https://ja.react.dev/reference/react/use
import { use, useState } from 'react';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
// 専用プロミスコンポーネント
import PromiseWrapper from '@/utils/libs/WrapperComponents/PromiseWrapper';

// 読み込み中表示
const Loading = () => (<p>Loading...</p>)

// レスポンスデータ定義
type LoaderResponseType = {
    id: number;
    type: string;
    name: string;
    params: string;
};
//
// 成功時の表示コンポーネント
const SuccessComponent = ({ data }: { data: LoaderResponseType }) => {
    return (
        <>
            <ul data-testid='response-info'>
                <li>Id: {data?.id}</li>
                <li>Type: {data?.type}</li>
                <li>Name: {data?.name}</li>
            </ul>
        </>
    );
};

// エラー時の表示コンポーネント
const ShowError = ({ error, resetErrorBoundary }: { error: Error; resetErrorBoundary: () => void }) => {
    console.debug('FetchUse ShowError called');
    return (
        <div role="alert">
            <p>FetchUse Component Error</p>
            <pre>{error.message}</pre>
            <Button color='error' variant='contained' onClick={resetErrorBoundary} data-testid='request-button'>
                再リクエスト
            </Button>
        </div>
    );
};

// プロミスを受け取って、useでレスポンスを扱うコンポーネント
const PickupDataComponent = ({ response_promise }: { response_promise: Promise<LoaderResponseType> }) => {
    const data = use(response_promise) as LoaderResponseType;
    return (
        <SuccessComponent data={data} />
    );
};

const getData = (key: boolean): Promise<LoaderResponseType> => {
    return fetch(`/static.json?key=${key}`)
        .then((response) => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then((data) => {
            if (!key) {
                throw new Error('意図的なエラー発生');
            }
            return { ...data };
        })
        .catch((error) => {
            console.error('Fetch error:', error);
            throw error;
            // return { response: null, error: error.message };
        });
};

// レンダリングページコンポーネント
export const FetchUse: React.FC = () => {
    // keyをトグルして、意図的にエラーを発生させる
    const [key, setKey] = useState(true);
    const onClick = () => { setKey(c => !c) };

    return (
        <>
            { /* PromiseWrapper コンポーネントを使用するパターン */}
            <Typography variant='h4' data-testid='fetch-component-title'>PromiseWrapper</Typography>
            <PromiseWrapper loading_fallback={<Loading />} error_fallback={ShowError} onReset={onClick}>
                <PickupDataComponent response_promise={getData(key)} />
            </PromiseWrapper>
            <Button color='secondary' variant='contained' onClick={onClick} data-testid='request-button'>
                リクエスト
            </Button>
        </>
    );
};



export default FetchUse;