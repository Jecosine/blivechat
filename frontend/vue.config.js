/*
 * @Date: 2022-02-14 07:13:12
 * @LastEditors: Jecosine
 * @LastEditTime: 2022-02-14 07:14:42
 */
module.exports = {
  devServer: {
    proxy: {
      "/api": {
        target: "http://localhost:12450/",
        // 允许跨域
        changeOrigin: true,
        ws: true,
        pathRewrite: {
          // "^/api": "",
        },
      },
    },
  },
};
