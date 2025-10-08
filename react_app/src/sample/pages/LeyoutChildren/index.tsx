// React
/* eslint-disable @typescript-eslint/no-unused-vars */
import { useState, useEffect, useCallback, memo, Fragment, useMemo } from 'react';
// MUI Components
import { Container, Switch, Box, Button, TextField } from '@mui/material';

const InItem = ({ head }: { head: string }) => {
    const [time, setTime] = useState(0);
    // 1秒ごとにカウントアップする関数
    // 100msごとにcountUp関数を実行するタイマーをセット
    // console.log(`InItem render head: ${head} / time: ${time}`);
    useEffect(() => {
        const timer = setInterval(() => setTime(c => c + 1), 1000);
        console.log(`InItem useEffect head: ${head} / time: ${time}`);
        return () => clearInterval(timer)
    }, []);

    return (
        <>
            <h1>{`${head}: ${time}`}s</h1>
        </>
    );
};

const WrapItem = ({ children, toggle, keyTag }: { children: React.ReactNode; toggle: boolean; keyTag: string }) => {
    const color = toggle ? 'lightblue' : 'lightgreen';
    const WrapInKey = `WrapInKey_${keyTag}`;
    const WrapOutKey = `WrapOutKey_${keyTag}`;
    if (toggle) {
        return (
            <Fragment>
                <Box key={WrapOutKey}>
                    <Box key={WrapInKey}>{children}</Box>
                </Box>
            </Fragment>
        );
    } else {
        return (
            <Box key={WrapOutKey} sx={{ backgroundColor: color, p: 2, m: 1 }}>
                <Box key={WrapInKey}>{children}</Box>
            </Box>
        );
    }
}

export const LeyoutChildren: React.FC = () => {
    // コンポーネントを再定義
    // toggleの状態を管理するためのuseStateフック
    const [toggle, setToggle] = useState(false);
    // 型はそのまま伝搬するため、anyを使用
    // eslint-disable-next-line 
    const Comp = (s: any) => InItem(s);
    // メモコールバック関数を定義
    // eslint-disable-next-line 
    const UseCallbackComp = useCallback((s: any) => InItem(s), []);

    const useMemoComp = useMemo(() => {
        return <InItem key={`UseMemoComp`} head={"UseMemoComp"} />;
    }, []);

    return (
        <Container>
            <h1>Leyout Children</h1>
            <Switch
                checked={toggle}
                onChange={() => setToggle(c => !c)}
            />
            <p>ラップ有り</p>
            <WrapItem toggle={toggle} keyTag="Comp" key="CompWrap_1">
                <Comp head="Comp" />
            </WrapItem>
            <WrapItem toggle={toggle} keyTag="InItem" key="InItemWrap_1">
                <InItem head="InItem" />
            </WrapItem>
            <WrapItem toggle={toggle} keyTag="UseCallbackComp" key="UseCallbackCompWrap_1">
                <UseCallbackComp head="MemoizedComp" />
            </WrapItem>
            <WrapItem toggle={toggle} keyTag="UseMemoComp" key="UseMemoCompWarp_1">
                <Box key="UseMemoCompWarp2">
                    {useMemoComp}
                </Box>
            </WrapItem>
        </Container>
    );
};

export default LeyoutChildren;