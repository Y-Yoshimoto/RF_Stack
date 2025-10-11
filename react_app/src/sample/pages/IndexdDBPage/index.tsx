// React
import React from 'react';
import { useState } from 'react';
// MUI Components
import { Container, Typography, Stack, Button, TextField, LinearProgress } from '@mui/material';

import { useIndexedDB } from '@/sample/hooks/indexedDBhook';


const T_IndexedDB = () => {
    // キーステート
    const [key, setKey] = useState('');
    // 登録回数
    const [count, setCount] = useState(0);
    // DBから取得したデータをセット
    const [data, setData] = useState();

    // IndexedDBのカスタムフックを使用
    const { upsertData, getData, deleteData, clearData, getAllData, isConnected } = useIndexedDB({});
    const registrationData = {
        id: count,
        key: key,
        data: `data`,
    };
    if (!isConnected) return <LinearProgress />
    return (
        <>
            <Typography variant='h4'>IndexedDB Component</Typography>
            {/* 登録用UI */}
            <Stack spacing={1} direction="row" sx={{ m: 2 }}>
                <TextField id="set-key" label="key" variant="outlined" size="small"
                    value={key} onChange={(e) => { setKey(e.target.value) }}
                    data-testid="set-key-input" />
                <Button variant='contained'
                    data-testid="add-button"
                    disabled={key === ''}
                    onClick={() => { upsertData(key, registrationData); setCount(c => c + 1) }}>Add Data</Button>
            </Stack>
            <pre>{`登録用データ: ${JSON.stringify(registrationData, null, " ")}`}</pre>
            {/* IndexedDB 操作用UI */}
            <Stack spacing={1} direction="row" sx={{ m: 2 }}>
                <Button variant='contained' data-testid='get-button' onClick={() => { getData(key, setData) }}>Get</Button>
                <Button variant='contained' data-testid='get-all-button' color="secondary" onClick={() => { getAllData(setData) }}>Get All</Button>
                <Button variant='contained' data-testid='delete-button' color="warning" onClick={() => { deleteData(key) }}>Delete</Button>
                <Button variant='contained' data-testid='clear-button' color="error" onClick={() => { clearData() }}>Clear All</Button>
            </Stack>
            {/* 取得データ表示 */}
            <pre>取得データ</pre>
            <pre data-testid="response-info">{`${JSON.stringify(data, null, " ")}`}</pre>
        </>
    );
};

export const IndexedDBSampleComponent: React.FC = () => {

    return (
        <Container>
            <T_IndexedDB />
        </Container>
    );
};

export default IndexedDBSampleComponent;