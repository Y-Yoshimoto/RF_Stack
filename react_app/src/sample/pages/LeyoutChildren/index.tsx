// React
import { useState, useEffect, Fragment, useMemo } from 'react';
// MUI Components
import { Container, Switch, Box } from '@mui/material';

type InItemProps = { head: string };

const InItem = ({ head }: InItemProps) => {
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

const WrapItem = ({ children, toggle, key_tag }: { children: React.ReactNode; toggle: boolean; key_tag: string }) => {
    const color = toggle ? 'lightblue' : 'lightgreen';
    const wrap_in_key = `wrap_in_key_${key_tag}`;
    const wrap_out_key = `wrap_out_key_${key_tag}`;
    if (toggle) {
        return (
            <Fragment>
                <Box key={wrap_out_key}>
                    <Box key={wrap_in_key}>{children}</Box>
                </Box>
            </Fragment>
        );
    } else {
        return (
            <Box key={wrap_out_key} sx={{ backgroundColor: color, p: 2, m: 1 }}>
                <Box key={wrap_in_key}>{children}</Box>
            </Box>
        );
    }
}

// InItemを関数として呼び出すラッパーコンポーネント
// render中に生成するとレンダリングごとに別コンポーネントとなるため(react-hooks/static-components)、モジュールレベルで定義する。
// ラップ構造がtoggleで切り替わる際にサブツリーごと再マウントされるため、画面上の挙動は変わらない。
const Comp = (props: InItemProps) => InItem(props);
const UseCallbackComp = (props: InItemProps) => InItem(props);

export const LeyoutChildren: React.FC = () => {
    // toggleの状態を管理するためのuseStateフック
    const [toggle, setToggle] = useState(false);

    const use_memo_comp = useMemo(() => {
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
            <WrapItem toggle={toggle} key_tag="Comp" key="CompWrap_1">
                <Comp head="Comp" />
            </WrapItem>
            <WrapItem toggle={toggle} key_tag="InItem" key="InItemWrap_1">
                <InItem head="InItem" />
            </WrapItem>
            <WrapItem toggle={toggle} key_tag="UseCallbackComp" key="UseCallbackCompWrap_1">
                <UseCallbackComp head="MemoizedComp" />
            </WrapItem>
            <WrapItem toggle={toggle} key_tag="UseMemoComp" key="UseMemoCompWarp_1">
                <Box key="UseMemoCompWarp2">
                    {use_memo_comp}
                </Box>
            </WrapItem>
        </Container>
    );
};

export default LeyoutChildren;